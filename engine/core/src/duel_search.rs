//! Bounded two-seat search over cards deducible from public play.

use std::collections::HashMap;

use crate::{Card, Game, Outcome, Suit};

const SEARCH_STATES: usize = 4_000;
const BRANCH_LIMIT: usize = 7;
const TERMINAL: i32 = 10_000;

fn card_bit(card: Card) -> u64 {
    1 << (card.suit as u8 * 13 + card.rank as u8)
}

fn mask(cards: &[Card]) -> u64 {
    cards.iter().fold(0, |bits, &card| bits | card_bit(card))
}

fn inferred_world(game: &Game, seat: usize) -> Option<Game> {
    if game.seats() != 2 || game.turn() != Some(seat) {
        return None;
    }
    let visible = game.table.iter().fold(
        mask(&game.hands[seat]) | mask(&game.discarded),
        |bits, play| bits | card_bit(play.card),
    );
    let inferred = Card::deck()
        .into_iter()
        .filter(|&card| visible & card_bit(card) == 0)
        .collect::<Vec<_>>();
    if inferred.len() != game.hands[1 - seat].len() {
        return None;
    }
    let mut world = game.clone();
    world.hands[1 - seat] = inferred;
    Some(world)
}

#[derive(Hash, Eq, PartialEq)]
struct Position {
    hands: [u64; 2],
    lead: u64,
    turn: usize,
    version: u32,
    depth: u8,
}

struct Search {
    seat: usize,
    remaining: usize,
    positions: HashMap<Position, i32>,
}

impl Search {
    fn value(&self, game: &Game) -> i32 {
        if let Some(outcome) = game.outcome() {
            return match outcome {
                Outcome::Donkey { seat } if seat == self.seat => -TERMINAL,
                Outcome::Donkey { .. } => TERMINAL,
                Outcome::AllSafe | Outcome::PlayLimit => 0,
            };
        }
        let mine = &game.hands[self.seat];
        let theirs = &game.hands[1 - self.seat];
        let suit_count = |hand: &[Card]| {
            let mut counts = [0_i32; 4];
            for card in hand {
                counts[card.suit as usize] += 1;
            }
            counts
        };
        let ours = suit_count(mine);
        let others = suit_count(theirs);
        let (mut our_unmatched, mut their_unmatched) = (0, 0);
        for suit in 0..4 {
            our_unmatched += if others[suit] == 0 { ours[suit] } else { 0 };
            their_unmatched += if ours[suit] == 0 { others[suit] } else { 0 };
        }
        let mut balance = theirs.len() as i32 - mine.len() as i32;
        if let Some(lead) = game.table.first() {
            // A played lead is still in the trick until the second card resolves it.
            balance += if lead.seat == self.seat { -1 } else { 1 };
        }
        20 * balance + 5 * (their_unmatched - our_unmatched)
    }

    fn successors(&self, game: &Game, seat: usize) -> Vec<(Card, Game)> {
        let mut candidates = Vec::new();
        for card in game.legal_moves(seat) {
            let mut next = game.clone();
            next.play(seat, card).expect("search uses only legal cards");
            candidates.push((card, next));
        }
        candidates.sort_by_key(|(_, next)| {
            let score = self.value(next);
            if seat == self.seat { -score } else { score }
        });
        candidates
    }

    fn visit(&mut self, game: &Game, depth: u8, mut alpha: i32, mut beta: i32) -> Option<i32> {
        self.remaining = self.remaining.checked_sub(1)?;
        let Some(turn) = game.turn().filter(|_| depth > 0) else {
            return Some(self.value(game));
        };
        let key = Position {
            hands: [mask(&game.hands[0]), mask(&game.hands[1])],
            lead: game.table.first().map_or(0, |play| card_bit(play.card)),
            turn,
            version: game.version(),
            depth,
        };
        if let Some(score) = self.positions.get(&key) {
            return Some(*score);
        }
        let initial = (alpha, beta);
        let maximizing = turn == self.seat;
        let mut result = if maximizing { -TERMINAL } else { TERMINAL };
        for (_, next) in self.successors(game, turn).into_iter().take(BRANCH_LIMIT) {
            let score = self.visit(&next, depth - 1, alpha, beta)?;
            if maximizing {
                result = result.max(score);
                alpha = alpha.max(result);
            } else {
                result = result.min(score);
                beta = beta.min(result);
            }
            if alpha >= beta {
                break;
            }
        }
        if initial.0 < result && result < initial.1 {
            self.positions.insert(key, result);
        }
        Some(result)
    }
}

/// Search progressively deeper, keeping the last completed depth under the node cap.
/// Publicly inferred cards, rather than the other seat's stored hand, feed the search.
pub fn story_duel_move(game: &Game, seat: usize, avoid: Option<Suit>) -> Option<Card> {
    let world = inferred_world(game, seat)?;
    let mut search = Search {
        seat,
        remaining: SEARCH_STATES,
        positions: HashMap::new(),
    };
    let mut candidates = search.successors(&world, seat);
    let mut chosen = candidates.first()?.0;
    if candidates.len() == 1 {
        return Some(chosen);
    }
    for depth in (2..=8).step_by(2) {
        let mut ranking = Vec::with_capacity(candidates.len());
        for (card, next) in &candidates {
            let Some(value) = search.visit(next, depth - 1, -TERMINAL - 1, TERMINAL + 1) else {
                return Some(chosen);
            };
            ranking.push((value, avoid == Some(card.suit), *card));
        }
        ranking.sort_by_key(|(value, avoids, _)| (-value, *avoids));
        chosen = ranking[0].2;
        if ranking[0].0 == TERMINAL {
            return Some(chosen);
        }
        candidates.sort_by_key(|(card, _)| ranking.iter().position(|entry| entry.2 == *card));
    }
    Some(chosen)
}
