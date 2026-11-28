use rand::{Rng, seq::SliceRandom};
use serde::{Deserialize, Serialize};

use crate::{Card, HouseRules, Suit};

const PLAY_LIMIT: u32 = 1_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
pub struct PlayedCard {
    pub seat: usize,
    pub card: Card,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(tag = "reason", rename_all = "snake_case")]
pub enum Outcome {
    Donkey { seat: usize },
    AllSafe,
    PlayLimit,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum Event {
    CardPlayed {
        seat: usize,
        card: Card,
    },
    TrickDiscarded {
        leader: usize,
        pile: Vec<PlayedCard>,
    },
    Vettu {
        cutter: usize,
        receiver: usize,
        pile: Vec<PlayedCard>,
    },
    PlayerEscaped {
        seat: usize,
        place: usize,
    },
    GameFinished {
        outcome: Outcome,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GameError {
    SeatCount,
    Finished,
    OutOfTurn,
    IllegalCard,
}

/// One play in a recorded match, used to re-run and validate replays.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Play {
    pub seat: usize,
    pub card: Card,
}

/// The first play in a replay that the rules reject.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReplayError {
    pub index: usize,
    pub error: GameError,
}

#[derive(Debug, Serialize)]
pub struct View<'a> {
    pub version: u32,
    pub turn: Option<usize>,
    pub outcome: Option<Outcome>,
    pub rules: HouseRules,
    pub card_counts: Vec<usize>,
    pub table: &'a [PlayedCard],
    pub escape_order: &'a [usize],
    pub hand: &'a [Card],
    pub legal_moves: Vec<Card>,
}

pub(crate) fn suit_bit(suit: Suit) -> u8 {
    1 << suit as u8
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Game {
    pub(crate) hands: Vec<Vec<Card>>,
    pub(crate) table: Vec<PlayedCard>,
    pub(crate) escape_order: Vec<usize>,
    pub(crate) turn: usize,
    pub(crate) version: u32,
    pub(crate) outcome: Option<Outcome>,
    #[serde(default)]
    pub(crate) rules: HouseRules,
    /// Cards from clean tricks, out of play for good. Public knowledge.
    #[serde(default)]
    pub(crate) discarded: Vec<Card>,
    /// Cards each seat picked up in a Vettu and still holds. Public knowledge.
    #[serde(default)]
    pub(crate) known: Vec<Vec<Card>>,
    /// Suits each seat has shown it does not hold, as bits of `suit_bit`.
    #[serde(default)]
    pub(crate) voids: Vec<u8>,
}

impl Game {
    pub fn deal(seats: usize, rng: &mut impl Rng) -> Result<Self, GameError> {
        Self::deal_with(seats, HouseRules::default(), rng)
    }

    pub fn deal_with(
        seats: usize,
        rules: HouseRules,
        rng: &mut impl Rng,
    ) -> Result<Self, GameError> {
        if !(2..=5).contains(&seats) {
            return Err(GameError::SeatCount);
        }

        let mut deck = Card::deck();
        deck.shuffle(rng);
        let mut hands = vec![Vec::new(); seats];
        for (index, card) in deck.into_iter().enumerate() {
            hands[index % seats].push(card);
        }
        let turn = hands
            .iter()
            .position(|hand| hand.contains(&Card::ACE_OF_SPADES))
            .expect("a complete deck contains the ace of spades");
        Ok(Self {
            hands,
            table: Vec::new(),
            escape_order: Vec::new(),
            turn,
            version: 0,
            outcome: None,
            rules,
            discarded: Vec::new(),
            known: vec![Vec::new(); seats],
            voids: vec![0; seats],
        })
    }

    pub fn turn(&self) -> Option<usize> {
        self.outcome.is_none().then_some(self.turn)
    }

    pub fn version(&self) -> u32 {
        self.version
    }

    pub fn outcome(&self) -> Option<Outcome> {
        self.outcome
    }

    pub fn rules(&self) -> HouseRules {
        self.rules
    }

    pub fn seats(&self) -> usize {
        self.hands.len()
    }

    pub fn view(&self, seat: usize) -> Option<View<'_>> {
        Some(View {
            version: self.version,
            turn: self.turn(),
            outcome: self.outcome,
            rules: self.rules,
            card_counts: self.hands.iter().map(Vec::len).collect(),
            table: &self.table,
            escape_order: &self.escape_order,
            hand: self.hands.get(seat)?,
            legal_moves: self.legal_moves(seat),
        })
    }

    pub fn legal_moves(&self, seat: usize) -> Vec<Card> {
        if self.turn() != Some(seat) {
            return Vec::new();
        }
        if self.version == 0 {
            return vec![Card::ACE_OF_SPADES];
        }

        let hand = &self.hands[seat];
        if let Some(lead) = self.table.first() {
            let matching: Vec<_> = hand
                .iter()
                .copied()
                .filter(|card| card.suit == lead.card.suit)
                .collect();
            if !matching.is_empty() {
                return matching;
            }
        }
        hand.clone()
    }

    /// Legal leads that another active seat has already shown it can cut.
    /// This uses disclosed voids and does not inspect another player's hand.
    pub fn exposed_leads(&self, seat: usize) -> Vec<Card> {
        if !self.table.is_empty() {
            return Vec::new();
        }
        let void_suits = self
            .voids
            .iter()
            .enumerate()
            .filter(|(other, _)| *other != seat && !self.escape_order.contains(other))
            .fold(0, |suits, (_, voids)| suits | *voids);
        self.legal_moves(seat)
            .into_iter()
            .filter(|card| void_suits & suit_bit(card.suit) != 0)
            .collect()
    }

    pub fn play(&mut self, seat: usize, card: Card) -> Result<Vec<Event>, GameError> {
        let turn = self.turn().ok_or(GameError::Finished)?;
        if seat != turn {
            return Err(GameError::OutOfTurn);
        }
        if !self.legal_moves(seat).contains(&card) {
            return Err(GameError::IllegalCard);
        }
        self.ensure_tracking();
        let index = self.hands[seat]
            .iter()
            .position(|held| *held == card)
            .expect("legal moves belong to the current hand");
        self.hands[seat].remove(index);
        if let Some(index) = self.known[seat].iter().position(|held| *held == card) {
            self.known[seat].remove(index);
        }
        self.version += 1;

        let cut = self
            .table
            .first()
            .is_some_and(|lead| lead.card.suit != card.suit);
        if let (true, Some(lead)) = (cut, self.table.first()) {
            self.voids[seat] |= suit_bit(lead.card.suit);
        }
        self.table.push(PlayedCard { seat, card });
        let mut events = vec![Event::CardPlayed { seat, card }];
        if cut || self.table.len() == self.hands.len() - self.escape_order.len() {
            self.resolve_trick(cut, &mut events);
        } else {
            self.turn = self.next_seat(seat);
        }
        if let Some(outcome) = self
            .outcome
            .or((self.version >= PLAY_LIMIT).then_some(Outcome::PlayLimit))
        {
            self.outcome = Some(outcome);
            events.push(Event::GameFinished { outcome });
        }
        Ok(events)
    }

    /// Re-run recorded plays from this state. Returns the final state and
    /// every event, or the first play the rules reject.
    pub fn replay(&self, plays: &[Play]) -> Result<(Self, Vec<Event>), ReplayError> {
        let mut game = self.clone();
        let mut events = Vec::new();
        for (index, play) in plays.iter().enumerate() {
            let produced = game
                .play(play.seat, play.card)
                .map_err(|error| ReplayError { index, error })?;
            events.extend(produced);
        }
        Ok((game, events))
    }

    /// Snapshots written before public tracking existed load with empty
    /// tracking; size it to the table before the next play.
    pub(crate) fn ensure_tracking(&mut self) {
        let seats = self.hands.len();
        self.known.resize_with(seats, Vec::new);
        self.voids.resize(seats, 0);
    }

    pub(crate) fn next_seat(&self, after: usize) -> usize {
        let seats = self.hands.len();
        (1..=seats)
            .map(|offset| (after + offset) % seats)
            .find(|&seat| !self.hands[seat].is_empty())
            .expect("play advances only while there are cards")
    }

    fn resolve_trick(&mut self, cut: bool, events: &mut Vec<Event>) {
        let pile = std::mem::take(&mut self.table);
        let led_suit = pile[0].card.suit;
        let rules = self.rules;
        let leader = pile
            .iter()
            .filter(|play| play.card.suit == led_suit)
            .max_by_key(|play| rules.strength(play.card.rank))
            .expect("the lead card is in the pile")
            .seat;

        if cut {
            for play in &pile {
                self.hands[leader].push(play.card);
                self.known[leader].push(play.card);
                self.voids[leader] &= !suit_bit(play.card.suit);
            }
        } else {
            self.discarded.extend(pile.iter().map(|play| play.card));
        }

        let mut escapes = Vec::new();
        for play in &pile {
            if self.hands[play.seat].is_empty() {
                self.escape_order.push(play.seat);
                escapes.push(Event::PlayerEscaped {
                    seat: play.seat,
                    place: self.escape_order.len(),
                });
            }
        }

        let resolution = if cut {
            Event::Vettu {
                cutter: pile.last().expect("a cut includes the cutting card").seat,
                receiver: leader,
                pile,
            }
        } else {
            Event::TrickDiscarded { leader, pile }
        };
        events.push(resolution);
        events.extend(escapes);

        match self.hands.len() - self.escape_order.len() {
            0 => self.outcome = Some(Outcome::AllSafe),
            1 => {
                self.outcome = Some(Outcome::Donkey {
                    seat: self.next_seat(leader),
                });
            }
            _ => {
                self.turn = if self.hands[leader].is_empty() {
                    self.next_seat(leader)
                } else {
                    leader
                };
            }
        }
    }
}

#[cfg(test)]
mod tests;
