//! Table selection for the matchmaking queue. Pure and deterministic, so the
//! Python worker only reads the queue, calls this, then claims the result
//! atomically in Redis.

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Candidate {
    pub id: String,
    pub wait_seconds: f64,
    /// Hidden skill (for example OpenSkill mu). Visible MMR also works.
    pub skill: f64,
    /// Members of one party share an id and are seated together or not at all.
    #[serde(default)]
    pub party: Option<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct TableConfig {
    /// Humans needed before a table forms. The worker lowers this once bots
    /// may fill the remaining seats.
    pub min_humans: usize,
    pub max_seats: usize,
    /// Skill gap allowed at zero wait, widened per second of the longest wait.
    pub base_window: f64,
    pub window_per_second: f64,
    /// After this wait the skill window is removed entirely.
    pub open_after_seconds: f64,
    /// Pairs that must never share a table (fair-play flags, blocks).
    pub avoid: Vec<(String, String)>,
}

impl Default for TableConfig {
    fn default() -> Self {
        Self {
            min_humans: 4,
            max_seats: 5,
            base_window: 6.0,
            window_per_second: 0.5,
            open_after_seconds: 30.0,
            avoid: Vec::new(),
        }
    }
}

struct Unit<'a> {
    members: Vec<&'a Candidate>,
    wait: f64,
    skill: f64,
}

fn units(candidates: &[Candidate]) -> Vec<Unit<'_>> {
    let mut units: Vec<Unit<'_>> = Vec::new();
    for candidate in candidates {
        let party = candidate.party.as_deref();
        let existing = party.and_then(|id| {
            units
                .iter_mut()
                .find(|unit| unit.members[0].party.as_deref() == Some(id))
        });
        match existing {
            Some(unit) => unit.members.push(candidate),
            None => units.push(Unit {
                members: vec![candidate],
                wait: 0.0,
                skill: 0.0,
            }),
        }
    }
    for unit in &mut units {
        let size = unit.members.len() as f64;
        unit.wait = unit
            .members
            .iter()
            .map(|member| member.wait_seconds)
            .fold(0.0, f64::max);
        unit.skill = unit.members.iter().map(|member| member.skill).sum::<f64>() / size;
    }
    units
}

/// Pick a table around the longest-waiting unit, or `None` if no valid table
/// exists yet. A party is never seated alone.
pub fn select_table(candidates: &[Candidate], config: &TableConfig) -> Option<Vec<String>> {
    let units = units(candidates);
    let primary = (0..units.len()).max_by(|left, right| {
        units[*left]
            .wait
            .total_cmp(&units[*right].wait)
            .then(right.cmp(left))
    })?;
    let anchor = &units[primary];
    let window = if anchor.wait >= config.open_after_seconds {
        f64::INFINITY
    } else {
        config.base_window + config.window_per_second * anchor.wait
    };
    let avoided = |left: &str, right: &str| {
        config
            .avoid
            .iter()
            .any(|(a, b)| (a == left && b == right) || (a == right && b == left))
    };

    let mut others: Vec<usize> = (0..units.len()).filter(|index| *index != primary).collect();
    others.sort_by(|left, right| {
        let gap = |index: usize| (units[index].skill - anchor.skill).abs();
        gap(*left).total_cmp(&gap(*right)).then(left.cmp(right))
    });

    // Exhaustive (bounded) search instead of greedy: taking the closest unit
    // first can block a valid full table (an avoided pair, a party that no
    // longer fits). Best = most seats, then the smallest total skill gap.
    let pool: Vec<usize> = others
        .into_iter()
        .filter(|&index| (units[index].skill - anchor.skill).abs() <= window)
        .collect();
    let mut search = Search {
        units: &units,
        pool: &pool,
        anchor: anchor.skill,
        max_seats: config.max_seats,
        avoided: &avoided,
        budget: SEARCH_BUDGET,
        best: (Vec::new(), anchor.members.len(), 0.0),
    };
    let mut seated: Vec<&Candidate> = anchor.members.clone();
    search.explore(0, &mut Vec::new(), &mut seated, 0.0);
    let (chosen, count, _) = search.best;

    let enough = count >= config.min_humans.max(1);
    let lone_party = chosen.is_empty() && anchor.members.len() > 1;
    (enough && !lone_party).then(|| {
        anchor
            .members
            .iter()
            .chain(chosen.iter().flat_map(|&index| units[index].members.iter()))
            .map(|member| member.id.clone())
            .collect()
    })
}

/// Table search nodes allowed per call; the queue head is small, so this is
/// a safety cap, not a tuning knob.
const SEARCH_BUDGET: usize = 20_000;

struct Search<'a, F: Fn(&str, &str) -> bool> {
    units: &'a [Unit<'a>],
    pool: &'a [usize],
    anchor: f64,
    max_seats: usize,
    avoided: &'a F,
    budget: usize,
    /// (chosen unit indexes, seats filled, total skill gap)
    best: (Vec<usize>, usize, f64),
}

impl<'a, F: Fn(&str, &str) -> bool> Search<'a, F> {
    fn explore(
        &mut self,
        from: usize,
        chosen: &mut Vec<usize>,
        seated: &mut Vec<&'a Candidate>,
        gap: f64,
    ) {
        let (_, best_seats, best_gap) = self.best;
        if seated.len() > best_seats || (seated.len() == best_seats && gap < best_gap) {
            self.best = (chosen.clone(), seated.len(), gap);
        }
        if seated.len() == self.max_seats {
            return;
        }
        for position in from..self.pool.len() {
            if self.budget == 0 {
                return;
            }
            self.budget -= 1;
            let unit = &self.units[self.pool[position]];
            if seated.len() + unit.members.len() > self.max_seats {
                continue;
            }
            let clash = unit
                .members
                .iter()
                .any(|member| seated.iter().any(|sat| (self.avoided)(&member.id, &sat.id)));
            if clash {
                continue;
            }
            chosen.push(self.pool[position]);
            seated.extend(unit.members.iter().copied());
            let extra = (unit.skill - self.anchor).abs();
            self.explore(position + 1, chosen, seated, gap + extra);
            seated.truncate(seated.len() - unit.members.len());
            chosen.pop();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn player(id: &str, wait: f64, skill: f64) -> Candidate {
        Candidate {
            id: id.to_owned(),
            wait_seconds: wait,
            skill,
            party: None,
        }
    }

    #[test]
    fn builds_around_the_longest_waiter_within_the_skill_window() {
        let queue = [
            player("a", 4.0, 25.0),
            player("b", 10.0, 26.0),
            player("c", 1.0, 40.0),
            player("d", 2.0, 24.0),
            player("e", 3.0, 27.0),
        ];
        let config = TableConfig::default();
        // b waited longest; window 6 + 5 = 11 excludes c (gap 14).
        let table = select_table(&queue, &config).unwrap();
        assert_eq!(table, ["b", "a", "e", "d"]);
    }

    #[test]
    fn window_opens_after_long_waits() {
        let queue = [
            player("a", 31.0, 25.0),
            player("b", 1.0, 60.0),
            player("c", 1.0, 70.0),
            player("d", 1.0, 80.0),
        ];
        let table = select_table(&queue, &TableConfig::default()).unwrap();
        assert_eq!(table.len(), 4);
    }

    #[test]
    fn avoided_pairs_never_share_a_table() {
        let queue = [
            player("a", 9.0, 25.0),
            player("b", 1.0, 25.0),
            player("c", 1.0, 25.0),
        ];
        let config = TableConfig {
            min_humans: 2,
            avoid: vec![("b".into(), "a".into())],
            ..TableConfig::default()
        };
        assert_eq!(select_table(&queue, &config).unwrap(), ["a", "c"]);
    }

    #[test]
    fn parties_stay_together_and_never_sit_alone() {
        let mut queue = vec![
            player("p1", 20.0, 25.0),
            player("p2", 5.0, 25.0),
            player("solo", 1.0, 25.0),
        ];
        queue[0].party = Some("x".into());
        queue[1].party = Some("x".into());
        let config = TableConfig {
            min_humans: 2,
            ..TableConfig::default()
        };
        assert_eq!(select_table(&queue, &config).unwrap(), ["p1", "p2", "solo"]);
        assert_eq!(select_table(&queue[..2], &config), None);
    }

    #[test]
    fn finds_a_full_table_that_closest_first_would_miss() {
        // "b" is closest to the anchor but may not sit with "c" or "d";
        // taking it first leaves 2 seats. Skipping it seats 4.
        let queue = [
            player("a", 20.0, 25.0),
            player("b", 1.0, 25.1),
            player("c", 1.0, 26.0),
            player("d", 1.0, 26.5),
            player("e", 1.0, 27.0),
        ];
        let config = TableConfig {
            max_seats: 4,
            avoid: vec![("b".into(), "c".into()), ("b".into(), "d".into())],
            ..TableConfig::default()
        };
        let table = select_table(&queue, &config).unwrap();
        assert_eq!(table, ["a", "c", "d", "e"]);
    }

    #[test]
    fn too_few_humans_waits() {
        let queue = [player("a", 3.0, 25.0), player("b", 3.0, 25.0)];
        assert_eq!(select_table(&queue, &TableConfig::default()), None);
        assert_eq!(select_table(&[], &TableConfig::default()), None);
    }
}
