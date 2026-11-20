use super::*;
use crate::{Rank, Suit};
use rand::{SeedableRng, rngs::StdRng};

fn card(rank: Rank, suit: Suit) -> Card {
    Card { rank, suit }
}

fn game_with(hands: Vec<Vec<Card>>, version: u32) -> Game {
    Game {
        hands,
        table: Vec::new(),
        escape_order: Vec::new(),
        turn: 0,
        version,
        outcome: None,
    }
}

#[test]
fn opening_cut_returns_provisional_last_card_and_pile() {
    let cutter = card(Rank::King, Suit::Hearts);
    let mut game = game_with(
        vec![
            vec![Card::ACE_OF_SPADES],
            vec![cutter],
            vec![card(Rank::Two, Suit::Clubs)],
        ],
        0,
    );

    assert_eq!(game.play(0, cutter), Err(GameError::IllegalCard));
    game.play(0, Card::ACE_OF_SPADES).unwrap();
    assert_eq!(game.view(0).unwrap().card_counts, [0, 1, 1]);
    assert!(game.escape_order.is_empty());
    let events = game.play(1, cutter).unwrap();

    assert!(matches!(events.as_slice(), [
        Event::CardPlayed { seat: 1, .. },
        Event::Vettu { cutter: 1, receiver: 0, pile },
        Event::PlayerEscaped { seat: 1, place: 1 },
    ] if pile.len() == 2));
    assert_eq!(game.turn(), Some(0));
    assert_eq!(game.view(0).unwrap().hand, &[Card::ACE_OF_SPADES, cutter]);
}

#[test]
fn follow_suit_is_required_and_clean_winner_passes_lead_when_escaped() {
    let ace = Card::ACE_OF_SPADES;
    let low = card(Rank::Two, Suit::Spades);
    let king = card(Rank::King, Suit::Spades);
    let off_suit = card(Rank::Ace, Suit::Hearts);
    let mut game = game_with(
        vec![
            vec![ace],
            vec![low, off_suit],
            vec![king, card(Rank::Three, Suit::Clubs)],
        ],
        0,
    );

    assert_eq!(game.play(1, low), Err(GameError::OutOfTurn));
    game.play(0, ace).unwrap();
    assert_eq!(game.play(1, off_suit), Err(GameError::IllegalCard));
    assert_eq!(game.version(), 1);
    game.play(1, low).unwrap();
    let events = game.play(2, king).unwrap();
    assert!(matches!(
        events.as_slice(),
        [
            Event::CardPlayed { seat: 2, .. },
            Event::TrickDiscarded { leader: 0, .. },
            Event::PlayerEscaped { seat: 0, place: 1 },
        ]
    ));
    assert_eq!(game.turn(), Some(1));
    assert!(game.table.is_empty());
}

#[test]
fn simultaneous_escapes_take_precedence_over_play_limit() {
    let low = card(Rank::Two, Suit::Spades);
    let mut game = game_with(vec![vec![Card::ACE_OF_SPADES], vec![low]], PLAY_LIMIT - 2);
    game.play(0, Card::ACE_OF_SPADES).unwrap();
    let events = game.play(1, low).unwrap();
    assert_eq!(
        events.last(),
        Some(&Event::GameFinished {
            outcome: Outcome::AllSafe
        })
    );
    assert_eq!(game.escape_order, [0, 1]);
    assert_eq!(game.turn(), None);
}

#[test]
fn last_player_holding_cards_is_donkey() {
    let low = card(Rank::Two, Suit::Spades);
    let mut game = game_with(
        vec![
            vec![Card::ACE_OF_SPADES],
            vec![low, card(Rank::Ten, Suit::Clubs)],
        ],
        0,
    );
    game.play(0, Card::ACE_OF_SPADES).unwrap();
    let events = game.play(1, low).unwrap();
    assert_eq!(
        events.last(),
        Some(&Event::GameFinished {
            outcome: Outcome::Donkey { seat: 1 }
        })
    );
    assert_eq!(game.play(1, low), Err(GameError::Finished));
}

#[test]
fn seeded_games_conserve_cards_until_a_terminal_result() {
    for seats in 2..=5 {
        for seed in 0..25 {
            let mut rng = StdRng::seed_from_u64(seed);
            let mut game = Game::deal(seats, &mut rng).unwrap();
            let mut discarded = Vec::new();
            while let Some(seat) = game.turn() {
                let legal = game.legal_moves(seat);
                let card = legal[rng.random_range(0..legal.len())];
                for event in game.play(seat, card).unwrap() {
                    if let Event::TrickDiscarded { pile, .. } = event {
                        discarded.extend(pile.into_iter().map(|play| play.card));
                    }
                }
                let held = game.hands.iter().flatten().copied();
                let table = game.table.iter().map(|play| play.card);
                let cards: Vec<_> = held.chain(table).chain(discarded.iter().copied()).collect();
                assert_eq!(cards.len(), 52);
                assert!(Card::deck().iter().all(|card| cards.contains(card)));
            }
            assert!(game.version() <= PLAY_LIMIT);
        }
    }
}
