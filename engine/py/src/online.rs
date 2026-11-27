use donke_core::{Card, Game, HouseRules, Play, Suit};
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
};
use rand::{SeedableRng, rngs::StdRng};

use super::{code, rng, to_json};

#[pyclass]
pub(crate) struct OnlineGame {
    game: Game,
}

#[pymethods]
impl OnlineGame {
    #[new]
    #[pyo3(signature = (seats, ace_low=false))]
    fn new(seats: usize, ace_low: bool) -> PyResult<Self> {
        let game = Game::deal_with(seats, HouseRules { ace_low }, &mut rand::rng())
            .map_err(|error| PyValueError::new_err(code(error)))?;
        Ok(Self { game })
    }

    /// A reproducible offline deal for evaluations and demo replays.
    #[staticmethod]
    #[pyo3(signature = (seats, seed, ace_low=false))]
    fn seeded(seats: usize, seed: u64, ace_low: bool) -> PyResult<Self> {
        let game = Game::deal_with(
            seats,
            HouseRules { ace_low },
            &mut StdRng::seed_from_u64(seed),
        )
        .map_err(|error| PyValueError::new_err(code(error)))?;
        Ok(Self { game })
    }

    #[staticmethod]
    fn restore(snapshot: &str) -> PyResult<Self> {
        let game = serde_json::from_str(snapshot)
            .map_err(|_| PyRuntimeError::new_err("invalid_snapshot"))?;
        Ok(Self { game })
    }

    #[getter]
    fn turn(&self) -> Option<usize> {
        self.game.turn()
    }

    fn snapshot(&self) -> PyResult<String> {
        serde_json::to_string(&self.game).map_err(|_| PyRuntimeError::new_err("invalid_snapshot"))
    }

    fn view(&self, seat: usize) -> PyResult<String> {
        let view = self
            .game
            .view(seat)
            .ok_or_else(|| PyValueError::new_err("invalid_seat"))?;
        serde_json::to_string(&view).map_err(|_| PyRuntimeError::new_err("invalid_view"))
    }

    /// Play a card. Without a card, play the timeout auto-move (lowest card).
    #[pyo3(signature = (seat, card_json=None))]
    fn play(&mut self, py: Python<'_>, seat: usize, card_json: Option<&str>) -> PyResult<String> {
        let card = match card_json {
            Some(value) => serde_json::from_str::<Card>(value)
                .map_err(|_| PyValueError::new_err("invalid_card"))?,
            None => self
                .game
                .legal_moves(seat)
                .into_iter()
                .min_by_key(|card| self.game.rules().strength(card.rank))
                .ok_or_else(|| PyValueError::new_err("out_of_turn"))?,
        };
        let events = py
            .detach(|| self.game.play(seat, card))
            .map_err(|error| PyValueError::new_err(code(error)))?;
        serde_json::to_string(&events).map_err(|_| PyRuntimeError::new_err("invalid_events"))
    }

    /// The card a bot at `seat` would play, as JSON, or `None` off turn.
    #[pyo3(signature = (seat, level="hard", iterations=300, seed=None))]
    fn bot_move(
        &self,
        py: Python<'_>,
        seat: usize,
        level: &str,
        iterations: u32,
        seed: Option<u64>,
    ) -> PyResult<Option<String>> {
        let level = super::level(level)?;
        let card =
            py.detach(|| donke_core::bot_move(&self.game, seat, level, iterations, &mut rng(seed)));
        card.map(|card| to_json(&card)).transpose()
    }

    /// A bounded search policy for a two-player story duel.
    #[pyo3(signature = (seat, avoid_suit=None))]
    fn story_move(
        &self,
        py: Python<'_>,
        seat: usize,
        avoid_suit: Option<&str>,
    ) -> PyResult<Option<String>> {
        let avoid = match avoid_suit {
            None => None,
            Some("Clubs") => Some(Suit::Clubs),
            Some("Diamonds") => Some(Suit::Diamonds),
            Some("Hearts") => Some(Suit::Hearts),
            Some("Spades") => Some(Suit::Spades),
            Some(_) => return Err(PyValueError::new_err("unknown_suit")),
        };
        py.detach(|| donke_core::story_duel_move(&self.game, seat, avoid))
            .map(|card| to_json(&card))
            .transpose()
    }

    /// Every legal move for `seat` with its safe rate, best first, as JSON.
    #[pyo3(signature = (seat, iterations=300, seed=None))]
    fn evaluate(
        &self,
        py: Python<'_>,
        seat: usize,
        iterations: u32,
        seed: Option<u64>,
    ) -> PyResult<String> {
        let scores =
            py.detach(|| donke_core::evaluate(&self.game, seat, iterations, &mut rng(seed)));
        to_json(&scores)
    }

    /// Each seat's chance of avoiding the Donkey from public information.
    #[pyo3(signature = (iterations=400, seed=None))]
    fn win_chances(&self, py: Python<'_>, iterations: u32, seed: Option<u64>) -> Vec<f64> {
        py.detach(|| donke_core::win_chances(&self.game, iterations, &mut rng(seed)))
    }

    /// Re-run recorded plays from this state. Returns `{snapshot, events}` as
    /// JSON, or raises `ValueError("invalid_replay:<index>:<code>")`.
    fn replay(&self, py: Python<'_>, plays_json: &str) -> PyResult<String> {
        let plays: Vec<Play> =
            serde_json::from_str(plays_json).map_err(|_| PyValueError::new_err("invalid_plays"))?;
        let (game, events) = py.detach(|| self.game.replay(&plays)).map_err(|error| {
            PyValueError::new_err(format!(
                "invalid_replay:{}:{}",
                error.index,
                code(error.error)
            ))
        })?;
        to_json(&serde_json::json!({ "snapshot": game, "events": events }))
    }
}
