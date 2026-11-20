use donke_core::{Card, Game};
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
};

#[pyclass]
pub(crate) struct OnlineGame {
    game: Game,
}

#[pymethods]
impl OnlineGame {
    #[new]
    fn new(seats: usize) -> PyResult<Self> {
        let game = Game::deal(seats, &mut rand::rng())
            .map_err(|error| PyValueError::new_err(super::code(error)))?;
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

    #[pyo3(signature = (seat, card_json=None))]
    fn play(&mut self, py: Python<'_>, seat: usize, card_json: Option<&str>) -> PyResult<String> {
        let card = match card_json {
            Some(value) => serde_json::from_str::<Card>(value)
                .map_err(|_| PyValueError::new_err("invalid_card"))?,
            None => self
                .game
                .legal_moves(seat)
                .into_iter()
                .min_by_key(|card| card.rank)
                .ok_or_else(|| PyValueError::new_err("out_of_turn"))?,
        };
        let events = py
            .detach(|| self.game.play(seat, card))
            .map_err(|error| PyValueError::new_err(super::code(error)))?;
        serde_json::to_string(&events).map_err(|_| PyRuntimeError::new_err("invalid_events"))
    }
}
