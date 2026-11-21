import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_ai_coaching import played_replay
from test_multiplayer import prepare_match, ready_room
from test_online import headers, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.modules.ai.coaching import analyse, seat_of
from app.modules.identity.models import Player
from app.modules.identity.repository import apply_rating
from app.modules.matches.repository import MatchRepository
from app.modules.matches.schemas import GameSeat
from app.modules.matches.service import MatchService
from app.modules.matches.settlement import load_replay, persist
from app.modules.progression.models import PlayerSkill, Season, SeasonPlayer
from app.modules.progression.service import close_season

pytestmark = pytest.mark.integration


async def new_players(platform, count):
    async with platform.sessions.begin() as db:
        rows = [
            Player(google_sub=uuid4().hex, display_name=f"P{n}") for n in range(count)
        ]
        db.add_all(rows)
        await db.flush()
        return [row.id for row in rows]


def test_bot_takeover_moves_never_count_as_the_humans_decisions(settings):
    config = settings.model_copy(
        update={
            "room_start_seconds": 0,
            "turn_seconds": 0.001,
            "bot_turn_seconds": 0.001,
        }
    )
    with prepare_match(config) as client:
        players = [headers(sign_in(client)) for _ in range(2)]
        _, room_id = ready_room(client, players, capacity=3)

        async def play_out():
            async with open_platform(config) as platform:
                match = MatchService(platform)
                game = await match.start(room_id)
                for _ in range(1050):
                    await asyncio.sleep(0.002)
                    await match.tick()
                    state = await match.repo.get(game)
                    if state and state.status == "finished":
                        await match.settle(game)
                        return await load_replay(platform, game)
                raise AssertionError("Autoplay failed to finish a game")

        replay = asyncio.run(play_out())
    assert replay is not None
    humans = [i for i, seat in enumerate(replay.seats) if seat.player_id]
    assert all(replay.seats[i].bot for i in humans)  # both were taken over
    plays = [
        event
        for batch in replay.events
        for event in batch.events
        if event["event"] == "card_played" and event["seat"] in humans
    ]
    assert plays and all(event.get("auto") for event in plays)
    for index in humans:
        player = replay.seats[index].player_id
        assert player is not None and seat_of(replay, player) == index
        assert analyse(replay, index, iterations=20).decisions == 0


def test_leaving_a_match_still_costs_hidden_skill(settings):
    async def scenario():
        async with open_platform(settings) as platform:
            stays, leaves = await new_players(platform, 2)
            replay = played_replay(3, [stays, leaves, None])
            replay.seats[1] = GameSeat(
                player_id=leaves, display_name="Q", ready=True, bot=True, forfeited=True
            )
            assert await persist(platform, replay)
            async with platform.sessions() as db:
                return await db.get(PlayerSkill, stays), await db.get(
                    PlayerSkill, leaves
                )

    kept, left = asyncio.run(scenario())
    assert left is not None and left.matches == 1  # the leaver is rated
    assert kept is not None and left.mu < 25 < kept.mu  # ranked last


def test_closing_a_late_season_never_rewrites_the_running_seasons_ratings(settings):
    now = datetime.now(UTC)

    async def scenario():
        async with open_platform(settings) as platform:
            (player,) = await new_players(platform, 1)
            async with platform.sessions.begin() as db:
                old = Season(
                    theme="Old",
                    starts_at=now - timedelta(days=40),
                    ends_at=now - timedelta(days=10),
                )
                running = Season(
                    theme="Running",
                    starts_at=now - timedelta(days=10),
                    ends_at=now + timedelta(days=18),
                )
                db.add_all([old, running])
                await db.flush()
                db.add(SeasonPlayer(season_id=old.id, player_id=player, peak_mmr=1800))
                await apply_rating(db, player, 600)  # 1800, earned this season
            async with platform.sessions.begin() as db:
                info = await close_season(db, MatchRepository(platform), old.id, now)
            async with platform.sessions() as db:
                mmr = (await db.get(Player, player)).mmr
            async with platform.sessions.begin() as db:
                await db.delete(await db.get(Season, running.id))
                await db.delete(await db.get(Season, old.id))
            return info, mmr

    info, mmr = asyncio.run(scenario())
    assert info.closed_at is not None and info.ratings_reset is False
    assert mmr == 1800  # untouched: the reset would have made it 1500
