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
        rules: HouseRules::default(),
        discarded: Vec::new(),
        known: Vec::new(),
        voids: Vec::new(),
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
            assert_eq!(game.discarded, discarded);
        }
    }
}

#[test]
fn public_tracking_records_voids_pickups_and_discards() {
    let ace = Card::ACE_OF_SPADES;
    let two_spades = card(Rank::Two, Suit::Spades);
    let heart = card(Rank::Four, Suit::Hearts);
    let club = card(Rank::Five, Suit::Clubs);
    let mut game = game_with(
        vec![
            vec![ace, card(Rank::Three, Suit::Spades)],
            vec![two_spades, card(Rank::Six, Suit::Diamonds)],
            vec![heart, club],
        ],
        0,
    );
    game.play(0, ace).unwrap();
    game.play(1, two_spades).unwrap();
    // Seat 2 has no spades: a Vettu. Seat 0 holds the high spade and picks up.
    game.play(2, heart).unwrap();
    assert_eq!(game.voids[2], suit_bit(Suit::Spades));
    assert_eq!(game.known[0], [ace, two_spades, heart]);
    assert!(game.discarded.is_empty());
    // Playing a known card removes it from public knowledge.
    game.play(0, heart).unwrap();
    assert_eq!(game.known[0], [ace, two_spades]);
}

#[test]
fn ace_low_changes_who_picks_up_the_pile() {
    let ace = Card::ACE_OF_SPADES;
    let king = card(Rank::King, Suit::Spades);
    let cutter = card(Rank::Two, Suit::Hearts);
    let hands = vec![
        vec![ace, card(Rank::Three, Suit::Clubs)],
        vec![king, card(Rank::Four, Suit::Clubs)],
        vec![cutter, card(Rank::Five, Suit::Clubs)],
    ];
    let mut classic = game_with(hands.clone(), 0);
    let mut low = game_with(hands, 0);
    low.rules = HouseRules { ace_low: true };
    for game in [&mut classic, &mut low] {
        game.play(0, ace).unwrap();
        game.play(1, king).unwrap();
    }
    let receiver = |events: Vec<Event>| {
        events.into_iter().find_map(|event| match event {
            Event::Vettu { receiver, .. } => Some(receiver),
            _ => None,
        })
    };
    assert_eq!(receiver(classic.play(2, cutter).unwrap()), Some(0));
    assert_eq!(receiver(low.play(2, cutter).unwrap()), Some(1));
}

#[test]
fn replay_reproduces_the_match_and_reports_the_first_bad_play() {
    let mut rng = StdRng::seed_from_u64(7);
    let start = Game::deal(4, &mut rng).unwrap();
    let mut live = start.clone();
    let mut plays = Vec::new();
    while let Some(seat) = live.turn() {
        let legal = live.legal_moves(seat);
        let card = legal[rng.random_range(0..legal.len())];
        live.play(seat, card).unwrap();
        plays.push(Play { seat, card });
    }
    let (replayed, _) = start.replay(&plays).unwrap();
    assert_eq!(replayed.outcome(), live.outcome());
    assert_eq!(replayed.version(), live.version());

    let mut tampered = plays.clone();
    tampered[1].seat = tampered[0].seat;
    let error = start.replay(&tampered).unwrap_err();
    assert_eq!(error.index, 1);
    assert_eq!(error.error, GameError::OutOfTurn);
}

#[test]
fn snapshots_without_tracking_still_load_and_play() {
    let mut rng = StdRng::seed_from_u64(3);
    let game = Game::deal(3, &mut rng).unwrap();
    let mut value: serde_json::Value = serde_json::to_value(&game).unwrap();
    let object = value.as_object_mut().unwrap();
    for key in ["rules", "discarded", "known", "voids"] {
        object.remove(key);
    }
    let mut legacy: Game = serde_json::from_value(value).unwrap();
    let seat = legacy.turn().unwrap();
    legacy.play(seat, Card::ACE_OF_SPADES).unwrap();
    assert_eq!(legacy.known.len(), 3);
}
