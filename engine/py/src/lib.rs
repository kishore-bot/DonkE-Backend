mod online;

use donke_core::{
    BotLevel, Candidate, Card, ChatFilter as CoreChatFilter, Decision, Event, Game, GameError,
    HouseRules, TableConfig, bot_move,
};
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
};
use rand::{SeedableRng, rngs::StdRng};

fn code(error: GameError) -> &'static str {
    match error {
        GameError::SeatCount => "invalid_seat_count",
        GameError::Finished => "game_finished",
        GameError::OutOfTurn => "out_of_turn",
        GameError::IllegalCard => "illegal_card",
    }
}

fn level(name: &str) -> PyResult<BotLevel> {
    match name {
        "easy" => Ok(BotLevel::Easy),
        "medium" => Ok(BotLevel::Medium),
        "hard" => Ok(BotLevel::Hard),
        _ => Err(PyValueError::new_err("invalid_bot_level")),
    }
}

fn rng(seed: Option<u64>) -> StdRng {
    seed.map_or_else(StdRng::from_os_rng, StdRng::seed_from_u64)
}

fn to_json(value: &impl serde::Serialize) -> PyResult<String> {
    serde_json::to_string(value).map_err(|error| PyRuntimeError::new_err(error.to_string()))
}

#[pyclass]
struct PracticeGame {
    game: Game,
    level: BotLevel,
    iterations: u32,
}

impl PracticeGame {
    fn advance_bots(game: &mut Game, level: BotLevel, iterations: u32) -> Vec<Event> {
        let mut random = rng(None);
        let mut events = Vec::new();
        while let Some(seat) = game.turn().filter(|&seat| seat != 0) {
            let card = bot_move(game, seat, level, iterations, &mut random)
                .expect("the current bot has a legal play");
            events.extend(game.play(seat, card).expect("bots play legal cards"));
        }
        events
    }

    fn serialize(game: &Game, events: &[Event]) -> PyResult<String> {
        let view = game.view(0).expect("practice has a human at seat zero");
        to_json(&serde_json::json!({ "view": view, "events": events }))
    }
}

#[pymethods]
impl PracticeGame {
    #[new]
    #[pyo3(signature = (seats, level="easy", iterations=300, ace_low=false))]
    fn new(
        py: Python<'_>,
        seats: usize,
        level: &str,
        iterations: u32,
        ace_low: bool,
    ) -> PyResult<Self> {
        let level = self::level(level)?;
        let mut game = Game::deal_with(seats, HouseRules { ace_low }, &mut rand::rng())
            .map_err(|error| PyValueError::new_err(code(error)))?;
        py.detach(|| Self::advance_bots(&mut game, level, iterations));
        Ok(Self {
            game,
            level,
            iterations,
        })
    }

    #[getter]
    fn version(&self) -> u32 {
        self.game.version()
    }

    fn snapshot(&self) -> PyResult<String> {
        Self::serialize(&self.game, &[])
    }

    /// Score the human's legal moves (seat 0), best first, as JSON.
    #[pyo3(signature = (iterations=200, seed=None))]
    fn hint(&self, py: Python<'_>, iterations: u32, seed: Option<u64>) -> PyResult<String> {
        let scores = py.detach(|| donke_core::evaluate(&self.game, 0, iterations, &mut rng(seed)));
        to_json(&scores)
    }

    fn play(&self, py: Python<'_>, card_json: &str) -> PyResult<(Self, String)> {
        let card: Card =
            serde_json::from_str(card_json).map_err(|_| PyValueError::new_err("invalid_card"))?;
        let mut next = self.game.clone();
        let mut events = next
            .play(0, card)
            .map_err(|error| PyValueError::new_err(code(error)))?;
        let (level, iterations) = (self.level, self.iterations);
        events.extend(py.detach(|| Self::advance_bots(&mut next, level, iterations)));
        let response = Self::serialize(&next, &events)?;
        Ok((
            Self {
                game: next,
                level,
                iterations,
            },
            response,
        ))
    }
}

/// Aho-Corasick chat filter. Immutable, so one instance is safe to share.
#[pyclass(frozen)]
struct ChatFilter {
    filter: CoreChatFilter,
}

#[pymethods]
impl ChatFilter {
    #[new]
    fn new(words: Vec<String>) -> Self {
        Self {
            filter: CoreChatFilter::new(&words),
        }
    }

    fn censor(&self, text: &str) -> String {
        self.filter.censor(text)
    }

    fn contains(&self, text: &str) -> bool {
        self.filter.contains(text)
    }
}

#[pyfunction]
fn rank_passages(py: Python<'_>, query: String, passages: Vec<String>) -> Vec<usize> {
    py.detach(move || donke_core::rank_passages(&query, &passages))
}

/// Pick a table from queue candidates; returns player ids or `None`.
#[pyfunction]
#[pyo3(signature = (candidates_json, config_json=None))]
fn select_table(candidates_json: &str, config_json: Option<&str>) -> PyResult<Option<Vec<String>>> {
    let candidates: Vec<Candidate> = serde_json::from_str(candidates_json)
        .map_err(|_| PyValueError::new_err("invalid_candidates"))?;
    let config: TableConfig = match config_json {
        Some(value) => {
            serde_json::from_str(value).map_err(|_| PyValueError::new_err("invalid_config"))?
        }
        None => TableConfig::default(),
    };
    Ok(donke_core::select_table(&candidates, &config))
}

/// Fair-play statistics for a player's recent decisions, as JSON.
#[pyfunction]
fn fair_play_stats(py: Python<'_>, decisions_json: &str) -> PyResult<String> {
    let decisions: Vec<Decision> = serde_json::from_str(decisions_json)
        .map_err(|_| PyValueError::new_err("invalid_decisions"))?;
    to_json(&py.detach(|| donke_core::fair_play_stats(&decisions)))
}

#[pymodule(gil_used = true)]
fn donke_engine(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PracticeGame>()?;
    module.add_class::<online::OnlineGame>()?;
    module.add_class::<ChatFilter>()?;
    module.add_function(wrap_pyfunction!(rank_passages, module)?)?;
    module.add_function(wrap_pyfunction!(select_table, module)?)?;
    module.add_function(wrap_pyfunction!(fair_play_stats, module)?)?;
    Ok(())
}
