//! Bots, move evaluation and win chances.
//!
//! Search is determinized Monte Carlo: every iteration deals the cards a seat
//! cannot see into a world consistent with public knowledge (card counts,
//! discards, picked-up cards, shown voids), plays one candidate move, then
//! finishes the game with a fast heuristic playout. Root moves are chosen with
//! UCB1, so promising moves get more samples.

use rand::{
    Rng,
    seq::{IndexedRandom, SliceRandom},
};
use serde::{Deserialize, Serialize};

use crate::{
    Card, Game, Outcome,
    game::{PlayedCard, suit_bit},
};

/// Playout steps before an unfinished game counts as a draw.
const PLAYOUT_STEPS: usize = 600;
/// Chance a playout makes a random legal move instead of the heuristic one.
const PLAYOUT_NOISE: f64 = 0.2;
const EXPLORATION: f64 = 0.7;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BotLevel {
    /// Plays its lowest legal card.
    Easy,
    /// Ducks under the high card, dumps high cards on a Vettu.
    Medium,
    /// Monte Carlo search over determinized deals.
    Hard,
}

/// How a legal move fared in search.
#[derive(Clone, Copy, Debug, PartialEq, Serialize)]
pub struct MoveScore {
    pub card: Card,
    /// Share of samples in which the seat avoided being the Donkey.
    pub safe_rate: f64,
    pub visits: u32,
}

fn card_index(card: Card) -> usize {
    card.suit as usize * 13 + card.rank as usize
}

fn reward(outcome: Option<Outcome>, seat: usize) -> f64 {
    match outcome {
        Some(Outcome::Donkey { seat: donkey }) => f64::from(u8::from(donkey != seat)),
        Some(Outcome::AllSafe) => 1.0,
        Some(Outcome::PlayLimit) | None => 0.5,
    }
}

/// Medium bot: lead low, duck under the high card when following, dump the
/// highest card when last to act or when cutting.
pub fn heuristic_move(game: &Game, seat: usize) -> Option<Card> {
    let moves = game.legal_moves(seat);
    let strength = |card: &Card| game.rules.strength(card.rank);
    let Some(lead) = game.table.first() else {
        return moves.iter().copied().min_by_key(strength);
    };
    let following = moves.iter().any(|card| card.suit == lead.card.suit);
    if !following {
        return moves.iter().copied().max_by_key(strength);
    }
    let active = game.hands.len() - game.escape_order.len();
    if game.table.len() + 1 == active {
        return moves.iter().copied().max_by_key(strength);
    }
    let high = game
        .table
        .iter()
        .filter(|play: &&PlayedCard| play.card.suit == lead.card.suit)
        .map(|play| strength(&play.card))
        .max()
        .unwrap_or(0);
    moves
        .iter()
        .copied()
        .filter(|card| strength(card) < high)
        .max_by_key(strength)
        .or_else(|| moves.iter().copied().max_by_key(strength))
}

fn easy_move(game: &Game, seat: usize) -> Option<Card> {
    game.legal_moves(seat)
        .into_iter()
        .min_by_key(|card| game.rules.strength(card.rank))
}

/// Deal every card `observer` cannot see into a world that agrees with public
/// knowledge. With no observer, every hand is hidden (a spectator's view).
pub(crate) fn determinize(game: &Game, observer: Option<usize>, rng: &mut impl Rng) -> Game {
    let mut world = game.clone();
    world.ensure_tracking();
    // Before the first play, the seat to act is known to hold the ace of spades.
    if world.version == 0 && !world.known[world.turn].contains(&Card::ACE_OF_SPADES) {
        let opener = world.turn;
        world.known[opener].push(Card::ACE_OF_SPADES);
    }
    let mut seen = [false; 52];
    let visible = world
        .discarded
        .iter()
        .chain(world.table.iter().map(|play| &play.card));
    for card in visible {
        seen[card_index(*card)] = true;
    }
    if let Some(seat) = observer {
        for card in &world.hands[seat] {
            seen[card_index(*card)] = true;
        }
    }
    let hidden: Vec<usize> = (0..world.hands.len())
        .filter(|seat| Some(*seat) != observer)
        .collect();
    for &seat in &hidden {
        for card in &world.known[seat] {
            seen[card_index(*card)] = true;
        }
    }
    let mut pool: Vec<Card> = Card::deck()
        .into_iter()
        .filter(|card| !seen[card_index(*card)])
        .collect();
    pool.shuffle(rng);

    // Seats with the most shown voids are the hardest to fill; deal them first.
    let mut order = hidden;
    order.sort_by_key(|seat| std::cmp::Reverse(world.voids[*seat].count_ones()));
    for seat in order {
        let needed = world.hands[seat]
            .len()
            .saturating_sub(world.known[seat].len());
        let voids = world.voids[seat];
        let mut drawn = Vec::with_capacity(needed);
        let mut index = 0;
        while drawn.len() < needed && index < pool.len() {
            if voids & suit_bit(pool[index].suit) == 0 {
                drawn.push(pool.swap_remove(index));
            } else {
                index += 1;
            }
        }
        // Facts can conflict after pickups; fall back to any unseen card.
        while drawn.len() < needed {
            match pool.pop() {
                Some(card) => drawn.push(card),
                None => break,
            }
        }
        if drawn.len() < needed {
            continue; // Not enough unseen cards: keep the real hand.
        }
        let mut hand = world.known[seat].clone();
        hand.extend(drawn);
        world.hands[seat] = hand;
    }
    world
}

fn playout(world: &mut Game, rng: &mut impl Rng) -> Option<Outcome> {
    for _ in 0..PLAYOUT_STEPS {
        let Some(seat) = world.turn() else { break };
        let random = if rng.random_bool(PLAYOUT_NOISE) {
            world.legal_moves(seat).choose(rng).copied()
        } else {
            None
        };
        let Some(card) = random.or_else(|| heuristic_move(world, seat)) else {
            break;
        };
        world
            .play(seat, card)
            .expect("playout moves come from legal moves");
    }
    world.outcome()
}

/// Score every legal move for `seat` with `iterations` determinized samples.
/// Sorted best first.
pub fn evaluate(game: &Game, seat: usize, iterations: u32, rng: &mut impl Rng) -> Vec<MoveScore> {
    let moves = game.legal_moves(seat);
    if moves.is_empty() {
        return Vec::new();
    }
    let mut totals = vec![0.0; moves.len()];
    let mut visits = vec![0u32; moves.len()];
    for round in 0..iterations {
        let pick = visits
            .iter()
            .position(|count| *count == 0)
            .unwrap_or_else(|| {
                let log_total = f64::from(round).ln();
                (0..moves.len())
                    .max_by(|left, right| {
                        let score = |index: usize| {
                            let count = f64::from(visits[index]);
                            totals[index] / count + EXPLORATION * (log_total / count).sqrt()
                        };
                        score(*left).total_cmp(&score(*right))
                    })
                    .expect("there is at least one legal move")
            });
        let mut world = determinize(game, Some(seat), rng);
        world
            .play(seat, moves[pick])
            .expect("the seat's own hand is never re-dealt");
        totals[pick] += reward(playout(&mut world, rng), seat);
        visits[pick] += 1;
    }
    let mut scores: Vec<MoveScore> = moves
        .iter()
        .enumerate()
        .map(|(index, card)| MoveScore {
            card: *card,
            safe_rate: if visits[index] == 0 {
                0.0
            } else {
                totals[index] / f64::from(visits[index])
            },
            visits: visits[index],
        })
        .collect();
    scores.sort_by(|left, right| {
        right
            .safe_rate
            .total_cmp(&left.safe_rate)
            .then(right.visits.cmp(&left.visits))
    });
    scores
}

/// The card a bot at `seat` plays, or `None` when it is not that seat's turn.
pub fn bot_move(
    game: &Game,
    seat: usize,
    level: BotLevel,
    iterations: u32,
    rng: &mut impl Rng,
) -> Option<Card> {
    let moves = game.legal_moves(seat);
    if moves.len() <= 1 {
        return moves.first().copied();
    }
    match level {
        BotLevel::Easy => easy_move(game, seat),
        BotLevel::Medium => heuristic_move(game, seat),
        BotLevel::Hard if iterations == 0 => heuristic_move(game, seat),
        BotLevel::Hard => evaluate(game, seat, iterations, rng)
            .first()
            .map(|score| score.card),
    }
}

/// Each seat's chance of avoiding the Donkey, from public information only.
pub fn win_chances(game: &Game, iterations: u32, rng: &mut impl Rng) -> Vec<f64> {
    let seats = game.hands.len();
    if let Some(outcome) = game.outcome() {
        return (0..seats).map(|seat| reward(Some(outcome), seat)).collect();
    }
    let mut totals = vec![0.0; seats];
    for _ in 0..iterations.max(1) {
        let mut world = determinize(game, None, rng);
        let outcome = playout(&mut world, rng);
        for (seat, total) in totals.iter_mut().enumerate() {
            *total += reward(outcome, seat);
        }
    }
    let samples = f64::from(iterations.max(1));
    totals
        .into_iter()
        .enumerate()
        .map(|(seat, total)| {
            if game.escape_order.contains(&seat) {
                1.0
            } else {
                total / samples
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{Rank, Suit};
    use rand::{SeedableRng, rngs::StdRng};

    fn advance(game: &mut Game, plays: usize) {
        for _ in 0..plays {
            let Some(seat) = game.turn() else { return };
            let card = heuristic_move(game, seat).unwrap();
            game.play(seat, card).unwrap();
        }
    }

    #[test]
    fn determinized_worlds_keep_counts_own_hand_and_public_cards() {
        let mut rng = StdRng::seed_from_u64(11);
        let mut game = Game::deal(4, &mut rng).unwrap();
        advance(&mut game, 30);
        let observer = game.turn().unwrap_or(0);
        for _ in 0..50 {
            let world = determinize(&game, Some(observer), &mut rng);
            assert_eq!(world.hands[observer], game.hands[observer]);
            for seat in 0..4 {
                assert_eq!(world.hands[seat].len(), game.hands[seat].len());
                for card in &game.known[seat] {
                    assert!(world.hands[seat].contains(card));
                }
            }
            let mut all: Vec<_> = world.hands.iter().flatten().copied().collect();
            all.extend(world.table.iter().map(|play| play.card));
            all.extend(world.discarded.iter().copied());
            assert_eq!(all.len(), 52);
            assert!(Card::deck().iter().all(|card| all.contains(card)));
        }
    }

    #[test]
    fn determinized_worlds_respect_shown_voids() {
        let mut rng = StdRng::seed_from_u64(5);
        let mut game = Game::deal(3, &mut rng).unwrap();
        game.ensure_tracking();
        game.voids[1] = suit_bit(Suit::Hearts);
        let observer = 0;
        // Seat 1 is dealt first and enough non-hearts are unseen, so the
        // void always holds.
        for _ in 0..50 {
            let world = determinize(&game, Some(observer), &mut rng);
            assert!(world.hands[1].iter().all(|card| card.suit != Suit::Hearts));
            assert_eq!(world.hands[1].len(), game.hands[1].len());
        }
    }

    #[test]
    fn evaluate_scores_every_legal_move_and_is_reproducible() {
        let mut rng = StdRng::seed_from_u64(21);
        let mut game = Game::deal(4, &mut rng).unwrap();
        advance(&mut game, 9);
        let seat = game.turn().unwrap();
        let first = evaluate(&game, seat, 200, &mut StdRng::seed_from_u64(1));
        let second = evaluate(&game, seat, 200, &mut StdRng::seed_from_u64(1));
        assert_eq!(first, second);
        assert_eq!(first.len(), game.legal_moves(seat).len());
        assert_eq!(first.iter().map(|score| score.visits).sum::<u32>(), 200);
        assert!(
            first
                .windows(2)
                .all(|pair| pair[0].safe_rate >= pair[1].safe_rate)
        );
    }

    #[test]
    fn bots_always_play_legal_cards_to_a_finish() {
        for level in [BotLevel::Easy, BotLevel::Medium, BotLevel::Hard] {
            for seed in 0..4 {
                let mut rng = StdRng::seed_from_u64(seed);
                let mut game = Game::deal(4, &mut rng).unwrap();
                while let Some(seat) = game.turn() {
                    let card = bot_move(&game, seat, level, 24, &mut rng).unwrap();
                    assert!(game.legal_moves(seat).contains(&card));
                    game.play(seat, card).unwrap();
                }
                assert!(game.outcome().is_some());
            }
        }
    }

    #[test]
    fn medium_ducks_under_the_high_card() {
        let ace = Card::ACE_OF_SPADES;
        let mut game = Game::deal(3, &mut StdRng::seed_from_u64(0)).unwrap();
        game.hands = vec![
            vec![ace],
            vec![
                Card {
                    suit: Suit::Spades,
                    rank: Rank::Queen,
                },
                Card {
                    suit: Suit::Spades,
                    rank: Rank::King,
                },
                Card {
                    suit: Suit::Hearts,
                    rank: Rank::Two,
                },
            ],
            vec![Card {
                suit: Suit::Clubs,
                rank: Rank::Two,
            }],
        ];
        game.turn = 0;
        game.version = 0;
        game.play(0, ace).unwrap();
        // Seat 1 cannot beat the ace; it dumps its highest spade under it.
        assert_eq!(
            heuristic_move(&game, 1),
            Some(Card {
                suit: Suit::Spades,
                rank: Rank::King
            })
        );
    }

    #[test]
    fn hard_bots_beat_easy_bots_over_many_games() {
        // Seat 0 is hard; the others play easy. Hard should be the Donkey
        // less often than the 1-in-4 share a random seat would get.
        let mut donkeys = 0;
        let games = 40;
        for seed in 0..games {
            let mut rng = StdRng::seed_from_u64(1_000 + seed);
            let mut game = Game::deal(4, &mut rng).unwrap();
            while let Some(seat) = game.turn() {
                let level = if seat == 0 {
                    BotLevel::Hard
                } else {
                    BotLevel::Easy
                };
                let card = bot_move(&game, seat, level, 60, &mut rng).unwrap();
                game.play(seat, card).unwrap();
            }
            if game.outcome() == Some(Outcome::Donkey { seat: 0 }) {
                donkeys += 1;
            }
        }
        assert!(
            donkeys * 4 < games,
            "hard bot was the Donkey {donkeys}/{games} times"
        );
    }

    #[test]
    fn playouts_reach_a_real_outcome() {
        let mut rng = StdRng::seed_from_u64(4);
        for _ in 0..20 {
            let mut world = Game::deal(4, &mut rng).unwrap();
            let outcome = playout(&mut world, &mut rng);
            assert!(matches!(
                outcome,
                Some(Outcome::Donkey { .. } | Outcome::AllSafe)
            ));
        }
        // Four seats, one Donkey at most: average safety is at least 3 in 4.
        let game = Game::deal(4, &mut rng).unwrap();
        let chances = win_chances(&game, 200, &mut rng);
        assert!(chances.iter().sum::<f64>() >= 2.9, "{chances:?}");
    }

    #[test]
    fn win_chances_are_probabilities_and_escaped_seats_are_safe() {
        let mut rng = StdRng::seed_from_u64(9);
        let mut game = Game::deal(3, &mut rng).unwrap();
        advance(&mut game, 12);
        let chances = win_chances(&game, 100, &mut rng);
        assert_eq!(chances.len(), 3);
        assert!(chances.iter().all(|chance| (0.0..=1.0).contains(chance)));
        for seat in &game.escape_order {
            assert_eq!(chances[*seat], 1.0);
        }
    }
}
