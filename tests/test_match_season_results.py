import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from test_multiplayer import prepare_match, ready_room
from test_online import headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.errors import AppError
from app.core.platform import open_platform
from app.modules.identity.models import Player
from app.modules.matches import settlement
from app.modules.matches.models import MatchPlayer
from app.modules.matches.schemas import (
    EventBatch,
    GameSeat,
    MatchAdmission,
    MatchReplay,
)
from app.modules.matches.service import MatchService
from app.modules.progression.calendar import week_start
from app.modules.progression.models import Season, SeasonDay, SeasonPlayer, WeeklyPlayer
from app.modules.progression.services.seasons import close_season

pytestmark = pytest.mark.integration


async def advance_to_deadline(matches, game_id):
    state = await matches.repo.get(game_id)
    assert state is not None
    state.deadline_ms = state.limit_ms = await matches.repo.now_ms() - 1
    await matches.platform.redis.set(
        matches.repo.game_key("state", game_id), state.model_dump_json()
    )
    await matches.on_deadline(game_id)


def test_match_reconnects_and_settles_in_original_season_after_rollover(settings):
    config = settings.model_copy(update={"room_start_seconds": 0})
    with prepare_match(config) as client:
        sessions = [sign_in(client) for _ in range(4)]
        auth = [headers(token) for token in sessions]
        player = UUID(profile(client, sessions[0])["id"])
        _, old_room = ready_room(client, auth[:2])
        _, next_room = ready_room(client, auth[2:])

        async def scenario():
            async with open_platform(config) as platform:
                matches = MatchService(platform)
                now = datetime.fromtimestamp(await matches.repo.now_ms() / 1000, UTC)
                old = Season(
                    theme="Old cast",
                    pack_key="grimoire-awakening-v1",
                    starts_at=now - timedelta(days=20),
                    ends_at=now + timedelta(hours=1),
                )
                upcoming = Season(
                    theme="New cast",
                    pack_key="skybound-voyage-v1",
                    starts_at=old.ends_at,
                    ends_at=old.ends_at + timedelta(days=21),
                )
                async with platform.sessions.begin() as db:
                    db.add_all([old, upcoming])
                try:
                    first = await matches.start(old_room)
                    assert first is not None
                    path = f"/api/v1/games/{first}"
                    assert (
                        client.get(path + "/result", headers=auth[0]).json()["status"]
                        == "in_progress"
                    )
                    assert (
                        client.get(path + "/result", headers=auth[2]).status_code == 404
                    )

                    boundary_ms = await matches.repo.now_ms() + 200
                    boundary = datetime.fromtimestamp(boundary_ms / 1000, UTC)
                    async with platform.sessions.begin() as db:
                        (await db.get(Season, old.id)).ends_at = boundary
                        (await db.get(Season, upcoming.id)).starts_at = boundary
                    seconds_left = (boundary_ms - await matches.repo.now_ms()) / 1000
                    await asyncio.sleep(max(0, seconds_left) + 0.025)

                    second = await matches.start(next_room)
                    assert (
                        await matches.repo.get(second)
                    ).admission.season_id == upcoming.id
                    with client.websocket_connect(
                        path + "/ws?after_sequence=1", headers=auth[0]
                    ) as socket:
                        sync = socket.receive_json()
                        assert sync["type"] == "state_sync"
                        assert sync["admission"] == {
                            "season_id": str(old.id),
                            "season_title": "Old cast",
                            "pack_key": "grimoire-awakening-v1",
                            "rules_version": "kazhutha-v1",
                        }

                    async def close():
                        async with platform.sessions.begin() as db:
                            return await close_season(
                                db, matches.repo, old.id, datetime.now(UTC)
                            )

                    with pytest.raises(AppError) as active:
                        await close()
                    assert active.value.code == "season_settlement_pending"
                    await advance_to_deadline(matches, first)
                    response = client.get(path + "/result", headers=auth[0])
                    assert response.json()["status"] == "pending"
                    assert response.headers["cache-control"] == "no-store"
                    await matches.repo.execute("defer_settlement", first)
                    with pytest.raises(AppError) as pending:
                        await close()
                    assert pending.value.code == "season_settlement_pending"

                    await asyncio.gather(matches.settle(first), matches.settle(first))
                    result = client.get(path + "/result", headers=auth[0]).json()
                    assert result["status"] == "settled"
                    assert result["rewarded_season_id"] == str(old.id)
                    assert result["outcome"] == "time_limit"
                    assert result["placement"] == "holding"
                    assert result["rewards"] == {
                        "coins": 10,
                        "season_points": 5,
                        "bank_coins": 2,
                        "mmr_delta": 0,
                    }
                    async with platform.sessions() as db:
                        assert (
                            await db.get(SeasonPlayer, (old.id, player))
                        ).points == 5
                        assert await db.get(SeasonPlayer, (upcoming.id, player)) is None
                    info = await close()
                    assert info.closed_at and not info.ratings_reset
                    assert (
                        client.get(path + "/result", headers=auth[0]).json() == result
                    )
                    replay = client.get(path + "/replay", headers=auth[0]).json()
                    assert replay["admission"] == result["admission"]
                    assert "opening" not in replay
                    recent = "/api/v1/games/results/recent"
                    assert client.get(recent, headers=auth[0]).json()[0][
                        "game_id"
                    ] == str(first)
                    assert client.get(recent, headers=auth[2]).json() == []
                finally:
                    async with platform.sessions.begin() as db:
                        await db.execute(
                            delete(Season).where(Season.id.in_((old.id, upcoming.id)))
                        )

        asyncio.run(scenario())


def test_late_rewards_use_final_season_day_and_legacy_receipts_omit_unknown_amounts(
    settings,
):
    with prepare_match(settings) as client:
        tokens = [sign_in(client) for _ in range(2)]
        players = [UUID(profile(client, token)["id"]) for token in tokens]
        auth = headers(tokens[0])
        starts = datetime(2041, 1, 1, tzinfo=UTC)
        ending = starts + timedelta(days=21)

        async def scenario():
            async with open_platform(settings) as platform:
                async with platform.sessions.begin() as db:
                    old = Season(
                        theme="Old pack",
                        pack_key="grimoire-awakening-v1",
                        starts_at=starts,
                        ends_at=ending,
                    )
                    db.add(old)
                    (await db.get(Player, players[0])).mmr = 1
                try:
                    replay = MatchReplay(
                        id=uuid4(),
                        room_id=uuid4(),
                        mode="ranked",
                        admission=MatchAdmission(
                            season_id=old.id, pack_key=old.pack_key
                        ),
                        seats=[
                            GameSeat(
                                player_id=player,
                                display_name="Player",
                                ready=True,
                                bot=False,
                            )
                            for player in players
                        ],
                        outcome={"reason": "donkey", "seat": 0},
                        events=[
                            EventBatch(
                                sequence=1,
                                events=[
                                    {"event": "player_escaped", "seat": 1, "place": 1}
                                ],
                            )
                        ],
                    )
                    finished = ending + timedelta(minutes=1)
                    assert await settlement.persist(
                        platform, replay, finished_at=finished
                    )
                    path = f"/api/v1/games/{replay.id}/result"
                    receipt = client.get(path, headers=auth).json()
                    assert receipt["placement"] == "donkey"
                    assert receipt["rewards"]["mmr_delta"] == -1
                    final_day = ending - timedelta(microseconds=1)
                    async with platform.sessions.begin() as db:
                        assert await db.get(
                            SeasonDay, (old.id, players[0], final_day.date())
                        )
                        assert (
                            await db.get(
                                SeasonDay, (old.id, players[0], finished.date())
                            )
                            is None
                        )
                        week = week_start(final_day, old)
                        assert (
                            await db.get(WeeklyPlayer, (old.id, players[0], week))
                        ).games == 1
                        (
                            await db.get(MatchPlayer, (replay.id, players[0]))
                        ).receipt = None
                    assert (legacy := client.get(path, headers=auth).json())[
                        "status"
                    ] == "settled"
                    assert legacy["placement"] == "donkey"
                    assert legacy["rewards"] is None
                    no_season = replay.model_copy(
                        update={
                            "id": uuid4(),
                            "mode": "classic",
                            "admission": MatchAdmission(season_id=None),
                        }
                    )
                    assert await settlement.persist(
                        platform, no_season, finished_at=ending - timedelta(minutes=1)
                    )
                    neutral = client.get(
                        f"/api/v1/games/{no_season.id}/result", headers=auth
                    ).json()
                    assert neutral["admission"]["season_id"] is None
                    assert neutral["rewarded_season_id"] is None
                    assert neutral["rewards"]["season_points"] == 0
                finally:
                    async with platform.sessions.begin() as db:
                        await db.delete(await db.get(Season, old.id))

        asyncio.run(scenario())
