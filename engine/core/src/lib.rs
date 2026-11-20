mod cards;
mod game;

pub use cards::{Card, Rank, Suit};
pub use game::{Event, Game, GameError, Outcome, View};
mod retrieval;

pub use retrieval::rank_passages;
