from datetime import date
from uuid import uuid4

import pytest

from app.modules.matches.schemas.results import MatchReplay
from app.modules.matches.schemas.state import EventBatch, GameSeat
from app.modules.progression.dto.rating import Rating
from app.modules.progression.helpers.catalog import (
    CATALOG,
    active_perks,
    bank_share,
    boosted_coins,
    in_window,
    tier_reached,
    window_end,
)
from app.modules.progression.helpers.skill import rate
from app.modules.progression.services.analytics import finishing_ranks, match_analytics


def seat(name, *, bot=False, forfeited=False):
    return GameSeat(
        player_id=None if bot else uuid4(),
        display_name=name,
        ready=True,
        bot=bot,
        forfeited=forfeited,
    )


def pile(*seats):
    return [
        {"seat": index, "card": {"suit": "Spades", "rank": "Two"}} for index in seats
    ]


def replay(events, outcome, seats=None):
    return MatchReplay(
        id=uuid4(),
        room_id=uuid4(),
        mode="classic",
        seats=seats or [seat("A"), seat("B"), seat("C", bot=True)],
        outcome=outcome,
        events=[EventBatch(sequence=1, events=events)],
    )


def test_analytics_counts_plays_vettus_pickups_places_and_badges():
    events = [
        {"event": "card_played", "seat": 0, "card": {}},
        {"event": "card_played", "seat": 1, "card": {}},
        {"event": "card_played", "seat": 2, "card": {}},
        {"event": "vettu", "cutter": 2, "receiver": 0, "pile": pile(0, 1, 2)},
        {"event": "card_played", "seat": 0, "card": {}},
        {"event": "vettu", "cutter": 1, "receiver": 0, "pile": pile(0, 1)},
        {"event": "player_escaped", "seat": 1, "place": 1},
        {"event": "player_escaped", "seat": 2, "place": 2},
    ]
    stats = match_analytics(replay(events, {"reason": "donkey", "seat": 0}))
    a, b, c = stats.seats
    assert (stats.total_plays, stats.total_vettus) == (4, 2)
    assert a.cards_picked == 5 and a.cuts_received == 2 and a.donkey
    assert a.badges == ["pile_magnet"]
    assert (b.place, c.place) == (1, 2)
    assert b.badges == [] and c.badges == []  # tied on Vettus given
    assert stats.biggest_pile is not None and stats.biggest_pile.cards == 3
    assert finishing_ranks(stats) == {1: 1, 2: 2, 0: 3}


def test_ranks_tie_players_still_holding_cards_and_put_leavers_last():
    seats = [seat("A"), seat("B"), seat("C", forfeited=True)]
    events = [{"event": "player_escaped", "seat": 1, "place": 1}]
    stats = match_analytics(replay(events, {"reason": "play_limit"}, seats))
    assert finishing_ranks(stats) == {1: 1, 0: 2, 2: 4}


def test_skill_rewards_winners_and_shrinks_uncertainty():
    before = [Rating(), Rating(), Rating()]
    after = rate(before, [1, 2, 3])
    assert after[0].mu > before[0].mu > after[2].mu
    assert all(new.sigma < old.sigma for new, old in zip(after, before, strict=True))
    tied = rate([Rating(), Rating()], [1, 1])
    assert tied[0].mu == pytest.approx(25.0)
    # Beating a much stronger player moves the rating more.
    upset = rate([Rating(20, 4), Rating(32, 4)], [1, 2])[0].mu - 20
    expected = rate([Rating(32, 4), Rating(20, 4)], [1, 2])[0].mu - 32
    assert upset > expected
    with pytest.raises(ValueError):
        rate([Rating()], [1, 2])


def test_festival_windows_and_wrapping_new_year():
    vishu = CATALOG["vishu_kani_frame"].window
    christmas = CATALOG["christmas_star_back"].window
    assert in_window(None, date(2026, 6, 1))
    assert in_window(vishu, date(2026, 4, 14))
    assert not in_window(vishu, date(2026, 11, 21))
    assert window_end(vishu, date(2026, 4, 2)) == date(2026, 4, 20)
    assert window_end(vishu, date(2026, 6, 1)) is None
    assert in_window(christmas, date(2026, 12, 25))
    assert in_window(christmas, date(2027, 1, 3))
    assert not in_window(christmas, date(2026, 11, 21))
    assert window_end(christmas, date(2026, 12, 25)) == date(2027, 1, 5)
    assert window_end(christmas, date(2027, 1, 2)) == date(2027, 1, 5)


def test_perks_unlock_by_tier_and_change_coins_and_bank():
    assert tier_reached(49) == 4 and tier_reached(10_000) == 30
    assert active_perks(49) == set()
    early, late = active_perks(50), active_perks(250)
    assert early == {"coin_boost"}
    assert late == {"coin_boost", "bank_boost", "season_emote"}
    assert boosted_coins(10, set()) == 10 and boosted_coins(15, early) == 16
    assert bank_share(20, early) == 4 and bank_share(20, late) == 5
