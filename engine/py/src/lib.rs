mod online;

use donke_core::{Card, Event, Game, GameError};
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
};

fn code(error: GameError) -> &'static str {
    match error {
        GameError::SeatCount => "invalid_seat_count",
        GameError::Finished => "game_finished",
        GameError::OutOfTurn => "out_of_turn",
        GameError::IllegalCard => "illegal_card",
    }
}

#[pyclass]
struct PracticeGame {
    game: Game,
}

impl PracticeGame {
    fn advance_bots(game: &mut Game) -> Result<Vec<Event>, GameError> {
        let mut events = Vec::new();
        while let Some(seat) = game.turn().filter(|&seat| seat != 0) {
            let card = game
                .legal_moves(seat)
                .into_iter()
                .min_by_key(|card| card.rank)
                .expect("the current bot has a legal play");
            events.extend(game.play(seat, card)?);
        }
        Ok(events)
    }

    fn serialize(game: &Game, events: &[Event]) -> PyResult<String> {
        let view = game.view(0).expect("practice has a human at seat zero");
        serde_json::to_string(&serde_json::json!({ "view": view, "events": events }))
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))
    }
}

#[pymethods]
impl PracticeGame {
    #[new]
    fn new(seats: usize) -> PyResult<Self> {
        let mut game = Game::deal(seats, &mut rand::rng())
            .map_err(|error| PyValueError::new_err(code(error)))?;
        Self::advance_bots(&mut game).map_err(|error| PyRuntimeError::new_err(code(error)))?;
        Ok(Self { game })
    }

    #[getter]
    fn version(&self) -> u32 {
        self.game.version()
    }

    fn snapshot(&self) -> PyResult<String> {
        Self::serialize(&self.game, &[])
    }

    fn play(&self, card_json: &str) -> PyResult<(Self, String)> {
        let card: Card =
            serde_json::from_str(card_json).map_err(|_| PyValueError::new_err("invalid_card"))?;
        let mut next = self.game.clone();
        let mut events = next
            .play(0, card)
            .map_err(|error| PyValueError::new_err(code(error)))?;
        events.extend(
            Self::advance_bots(&mut next).map_err(|error| PyRuntimeError::new_err(code(error)))?,
        );
        let response = Self::serialize(&next, &events)?;
        Ok((Self { game: next }, response))
    }
}

#[pyfunction]
fn rank_passages(py: Python<'_>, query: String, passages: Vec<String>) -> Vec<usize> {
    py.detach(move || donke_core::rank_passages(&query, &passages))
}

#[pymodule(gil_used = true)]
fn donke_engine(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PracticeGame>()?;
    module.add_class::<online::OnlineGame>()?;
    module.add_function(wrap_pyfunction!(rank_passages, module)?)?;
    Ok(())
}
