//! Fair-play statistics over a player's recent decisions. The engine only
//! measures; a moderator always decides.

use serde::{Deserialize, Serialize};

/// Decisions needed before the engine-match signal is trusted.
const ENGINE_MIN_DECISIONS: usize = 150;
/// Only decisions with at least this many legal cards say anything about skill.
const ENGINE_MIN_CHOICES: u32 = 3;
const ENGINE_MATCH_RATE: f64 = 0.90;
const ENGINE_POINTS: u32 = 40;
const TIMING_MIN_DECISIONS: usize = 100;
const TIMING_MEDIAN_MS: f64 = 800.0;
/// Coefficient of variation of think time; humans vary a lot.
const TIMING_SPREAD: f64 = 0.20;
const TIMING_POINTS: u32 = 25;

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Decision {
    pub think_ms: u32,
    pub legal_moves: u32,
    /// The card played was the engine's top-rated move.
    pub matched_engine_top: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Signal {
    pub name: &'static str,
    pub points: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct FairPlayStats {
    pub decisions: usize,
    pub engine_decisions: usize,
    pub engine_match_rate: Option<f64>,
    pub median_think_ms: Option<f64>,
    pub think_spread: Option<f64>,
    pub signals: Vec<Signal>,
    pub score: u32,
}

fn median(values: &mut [f64]) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    values.sort_by(f64::total_cmp);
    let middle = values.len() / 2;
    Some(if values.len().is_multiple_of(2) {
        (values[middle - 1] + values[middle]) / 2.0
    } else {
        values[middle]
    })
}

pub fn fair_play_stats(decisions: &[Decision]) -> FairPlayStats {
    let choices: Vec<&Decision> = decisions
        .iter()
        .filter(|decision| decision.legal_moves >= ENGINE_MIN_CHOICES)
        .collect();
    let engine_match_rate = (!choices.is_empty()).then(|| {
        let matched = choices
            .iter()
            .filter(|decision| decision.matched_engine_top)
            .count();
        matched as f64 / choices.len() as f64
    });

    let mut times: Vec<f64> = decisions
        .iter()
        .map(|decision| f64::from(decision.think_ms))
        .collect();
    let mean = (!times.is_empty()).then(|| times.iter().sum::<f64>() / times.len() as f64);
    let think_spread = mean.filter(|mean| *mean > 0.0).map(|mean| {
        let variance =
            times.iter().map(|time| (time - mean).powi(2)).sum::<f64>() / times.len() as f64;
        variance.sqrt() / mean
    });
    let median_think_ms = median(&mut times);

    let mut signals = Vec::new();
    if choices.len() >= ENGINE_MIN_DECISIONS
        && engine_match_rate.is_some_and(|rate| rate >= ENGINE_MATCH_RATE)
    {
        signals.push(Signal {
            name: "engine_match",
            points: ENGINE_POINTS,
        });
    }
    let robotic = median_think_ms.is_some_and(|median| median < TIMING_MEDIAN_MS)
        || think_spread.is_some_and(|spread| spread < TIMING_SPREAD);
    if decisions.len() >= TIMING_MIN_DECISIONS && robotic {
        signals.push(Signal {
            name: "timing",
            points: TIMING_POINTS,
        });
    }
    let score = signals
        .iter()
        .map(|signal| signal.points)
        .sum::<u32>()
        .min(100);
    FairPlayStats {
        decisions: decisions.len(),
        engine_decisions: choices.len(),
        engine_match_rate,
        median_think_ms,
        think_spread,
        signals,
        score,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn decision(think_ms: u32, legal_moves: u32, matched: bool) -> Decision {
        Decision {
            think_ms,
            legal_moves,
            matched_engine_top: matched,
        }
    }

    #[test]
    fn human_like_play_raises_no_signal() {
        let decisions: Vec<_> = (0..200)
            .map(|index| decision(1_500 + (index * 37 % 4_000), 4, index % 3 == 0))
            .collect();
        let stats = fair_play_stats(&decisions);
        assert!(stats.signals.is_empty());
        assert_eq!(stats.score, 0);
    }

    #[test]
    fn engine_perfect_fast_play_raises_both_signals() {
        let decisions: Vec<_> = (0..200).map(|_| decision(400, 4, true)).collect();
        let stats = fair_play_stats(&decisions);
        let names: Vec<_> = stats.signals.iter().map(|signal| signal.name).collect();
        assert_eq!(names, ["engine_match", "timing"]);
        assert_eq!(stats.score, 65);
        assert_eq!(stats.engine_match_rate, Some(1.0));
    }

    #[test]
    fn forced_moves_and_small_samples_do_not_count() {
        let forced: Vec<_> = (0..300).map(|_| decision(2_000, 1, true)).collect();
        assert_eq!(fair_play_stats(&forced).engine_decisions, 0);
        let few: Vec<_> = (0..20).map(|_| decision(100, 5, true)).collect();
        assert!(fair_play_stats(&few).signals.is_empty());
        assert_eq!(fair_play_stats(&[]).median_think_ms, None);
    }
}
