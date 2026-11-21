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

    let mut seated: Vec<&Candidate> = anchor.members.clone();
    let mut unit_count = 1;
    for index in others {
        let unit = &units[index];
        if seated.len() + unit.members.len() > config.max_seats
            || (unit.skill - anchor.skill).abs() > window
        {
            continue;
        }
        let clash = unit
            .members
            .iter()
            .any(|member| seated.iter().any(|sat| avoided(&member.id, &sat.id)));
        if clash {
            continue;
        }
        seated.extend(unit.members.iter().copied());
        unit_count += 1;
        if seated.len() == config.max_seats {
            break;
        }
    }

    let enough = seated.len() >= config.min_humans.max(1);
    let lone_party = unit_count == 1 && anchor.members.len() > 1;
    (enough && !lone_party).then(|| seated.into_iter().map(|member| member.id.clone()).collect())
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
    fn too_few_humans_waits() {
        let queue = [player("a", 3.0, 25.0), player("b", 3.0, 25.0)];
        assert_eq!(select_table(&queue, &TableConfig::default()), None);
        assert_eq!(select_table(&[], &TableConfig::default()), None);
    }
}
