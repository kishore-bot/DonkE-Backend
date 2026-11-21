import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_online import client as client  # noqa: PLC0414
from test_online import headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.modules.admin.service import AdminService
from app.modules.identity.repository import apply_rating
from app.modules.lobby.repository import LobbyRepository
from app.modules.lobby.service import LobbyService
from app.modules.matches.models import MatchRecord
from app.modules.matches.schemas import EventBatch, GameSeat, MatchReplay
from app.modules.matches.settlement import persist
from app.modules.progression.models import Season, SeasonPlayer, Wallet, WeeklyPlayer
from app.workers.matchmaking import match_once

pytestmark = pytest.mark.integration


def test_friends_and_parties_queue_as_a_unit(client, settings):
    tokens = [sign_in(client) for _ in range(3)]
    players = [headers(token) for token in tokens]
    ids = [profile(client, token)["id"] for token in tokens]
    assert (
        client.post(f"/api/v1/friends/{ids[1]}", headers=players[0]).status_code == 204
    )
    assert (
        client.get("/api/v1/friends", headers=players[1]).json()[0]["status"]
        == "incoming"
    )
    assert (
        client.put(f"/api/v1/friends/{ids[0]}", headers=players[1]).status_code == 204
    )
    party = client.post("/api/v1/parties", headers=players[0]).json()
    assert (
        client.post(f"/api/v1/parties/invite/{ids[1]}", headers=players[0]).status_code
        == 204
    )
    assert client.get("/api/v1/parties/invites", headers=players[1]).json() == [
        party["id"]
    ]
    path = f"/api/v1/parties/{party['id']}/join"
    assert client.post(path, headers=players[2]).status_code == 404
    assert (
        client.post("/api/v1/matchmaking/join", headers=players[1], json={}).status_code
        == 200
    )
    blocked = client.post(path, headers=players[1])
    assert (
        blocked.status_code == 409 and blocked.json()["error"]["code"] == "player_busy"
    )
    assert (
        client.post("/api/v1/matchmaking/cancel", headers=players[1]).status_code == 200
    )
    assert len(client.post(path, headers=players[1]).json()["members"]) == 2
    assert client.post("/api/v1/parties/queue", headers=players[1]).status_code == 403
    assert (
        client.post("/api/v1/parties/queue", headers=players[0]).json()["status"]
        == "queued"
    )
    assert (
        client.post("/api/v1/matchmaking/cancel", headers=players[1]).json()["status"]
        == "idle"
    )
    assert (
        client.get("/api/v1/matchmaking/status", headers=players[0]).json()["status"]
        == "idle"
    )
    assert client.post("/api/v1/parties/queue", headers=players[0]).status_code == 200

    async def match():
        async with open_platform(settings) as platform:
            return await match_once(
                LobbyService(LobbyRepository(platform.redis, settings))
            )

    assert asyncio.run(match()) == 1
    assigned = [
        client.get("/api/v1/matchmaking/status", headers=player).json()["room_id"]
        for player in players[:2]
    ]
    assert assigned[0] is not None and assigned[0] == assigned[1]
    seats = client.get(f"/api/v1/rooms/{assigned[0]}", headers=players[0]).json()[
        "seats"
    ]
    assert [seat["player_id"] for seat in seats if not seat["bot"]] == ids[:2]


def test_season_ledger_store_and_close_are_idempotent(client, settings):
    token = sign_in(client)
    user = headers(token)
    player = UUID(profile(client, token)["id"])

    async def admin_account():
        async with open_platform(settings) as platform:
            return await AdminService(platform).create_account(
                f"season-admin-{uuid4().hex[:8]}",
                "synthetic-season-admin",
                "admin",
                uuid4(),
            )

    admin = asyncio.run(admin_account())
    login = client.post(
        "/api/v1/admin/auth/login",
        json={"username": admin.username, "password": "synthetic-season-admin"},
    ).json()
    csrf = {"X-CSRF-Token": login["csrf_token"]}
    now = datetime.now(UTC)
    payload = {
        "theme": "Karkidakam",
        "starts_at": (now - timedelta(hours=1)).isoformat(),
        "ends_at": (now + timedelta(days=7)).isoformat(),
        "reason": "Test season",
    }
    assert client.post("/api/v1/admin/seasons", json=payload).status_code == 403
    created = client.post("/api/v1/admin/seasons", json=payload, headers=csrf)
    assert created.status_code == 201, created.text
    season_id = UUID(created.json()["id"])
    assert (
        client.post("/api/v1/admin/seasons", json=payload, headers=csrf).status_code
        == 409
    )

    async def settle_matches():
        async with open_platform(settings) as platform:
            async with platform.sessions.begin() as db:
                await apply_rating(db, player, 260)
            for _ in range(7):
                replay = MatchReplay(
                    id=uuid4(),
                    room_id=uuid4(),
                    mode=None,
                    seats=[
                        GameSeat(
                            player_id=player,
                            display_name="Player",
                            bot=False,
                            ready=True,
                        )
                    ],
                    outcome={"reason": "donkey", "seat": 1},
                    events=[
                        EventBatch(
                            sequence=1,
                            events=[{"event": "player_escaped", "seat": 0, "place": 1}],
                        )
                    ],
                )
                assert await persist(platform, replay)
                assert not await persist(platform, replay)

    asyncio.run(settle_matches())
    # 100 capped match coins + First Escape (20) + First Crown (25).
    assert client.get("/api/v1/store/wallet", headers=user).json() == {"coins": 145}
    buy = "/api/v1/store/monsoon_back/buy"
    assert client.post(buy, headers=user).json() == {"coins": 85}
    assert client.post(buy, headers=user).json() == {"coins": 85}
    assert (
        client.put("/api/v1/store/monsoon_back/equip", headers=user).status_code == 204
    )
    assert client.get("/api/v1/store/inventory", headers=user).json() == [
        "monsoon_back"
    ]
    assert (
        len(client.get("/api/v1/seasons/current", headers=user).json()["tiers"]) == 30
    )
    claim = f"/api/v1/seasons/{season_id}/tiers/1/claim"
    assert client.post(claim, headers=user).json() == {"credited": True}
    assert client.post(claim, headers=user).json() == {"credited": False}
    weekly = f"/api/v1/seasons/{season_id}/weekly/play_three/claim"
    assert client.post(weekly, headers=user).json() == {"credited": True}
    assert client.post(weekly, headers=user).json() == {"credited": False}
    close = f"/api/v1/admin/seasons/{season_id}/close"
    assert client.post(close, json={"reason": "Ended"}, headers=csrf).status_code == 409

    async def end_season():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            row = await db.get(Season, season_id)
            assert row
            row.ends_at = datetime.now(UTC) - timedelta(seconds=1)

    asyncio.run(end_season())
    closed = client.post(close, json={"reason": "Ended"}, headers=csrf)
    assert closed.status_code == 200, closed.text
    assert (
        client.post(close, json={"reason": "Retry"}, headers=csrf).json()
        == closed.json()
    )
    assert profile(client, token)["mmr"] == 1330
    assert client.get("/api/v1/store/wallet", headers=user).json() == {"coins": 211}
    assert (
        client.get(f"/api/v1/seasons/{season_id}/board", headers=user).json()[0][
            "peak_mmr"
        ]
        == 1460
    )


def test_delayed_matches_use_their_finish_time_for_progression(client, settings):
    player = UUID(profile(client, sign_in(client))["id"])
    monday = datetime(2020, 1, 6, tzinfo=UTC)
    sunday = monday - timedelta(seconds=1)

    async def replay_rollover():
        async with open_platform(settings) as platform:
            async with platform.sessions.begin() as db:
                previous = Season(
                    theme="Previous",
                    starts_at=monday - timedelta(days=7),
                    ends_at=monday,
                )
                following = Season(
                    theme="Following",
                    starts_at=monday,
                    ends_at=monday + timedelta(days=7),
                )
                db.add_all([previous, following])

            for time, count in [(monday, 10), (sunday, 11)]:
                for _ in range(count):
                    replay = MatchReplay(
                        id=uuid4(),
                        room_id=uuid4(),
                        mode=None,
                        seats=[
                            GameSeat(
                                player_id=player,
                                display_name="Player",
                                ready=True,
                                bot=False,
                            )
                        ],
                        outcome={"reason": "time_limit"},
                        events=[],
                    )
                    assert await persist(platform, replay, finished_at=time)

            async with platform.sessions() as db:
                archived = await db.get(MatchRecord, replay.id)
                assert archived is not None and archived.finished_at == sunday
                wallet = await db.get(Wallet, player)
                # 200 capped match coins plus the 30-coin "Regular" achievement.
                assert wallet is not None and wallet.coins == 230
                for season, week, games in [
                    (previous, previous.starts_at.date(), 11),
                    (following, monday.date(), 10),
                ]:
                    progress = await db.get(SeasonPlayer, (season.id, player))
                    weekly = await db.get(WeeklyPlayer, (season.id, player, week))
                    assert progress is not None and progress.points == games * 5
                    assert weekly is not None and weekly.games == games

    asyncio.run(replay_rollover())
