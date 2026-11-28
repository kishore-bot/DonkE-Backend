import asyncio
from datetime import UTC, datetime, timedelta
from itertools import count
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from test_online import TestGoogle, headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.main import create_app
from app.modules.matches.controllers import socket as matches_router
from app.modules.matches.services import settlement
from app.modules.matches.services.match import MatchService

pytestmark = pytest.mark.integration


def prepare_match(config):
    client = TestClient(create_app(config, TestGoogle()))
    return client


def ready_room(client, auth, capacity=2):
    room = client.post(
        "/api/v1/rooms", json={"capacity": capacity}, headers=auth[0]
    ).json()
    path = "/api/v1/rooms/" + room["id"]
    assert client.post(path + "/join", headers=auth[1]).status_code == 200
    for player in auth:
        assert (
            client.put(
                path + "/ready", json={"ready": True}, headers=player
            ).status_code
            == 200
        )
    return path, UUID(room["id"])


def test_socket_replays_events_without_replaying_a_move(settings):
    config = settings.model_copy(update={"room_start_seconds": 0})
    with prepare_match(config) as client:
        players = [headers(sign_in(client)) for _ in range(2)]
        path, room_id = ready_room(client, players)

        async def start():
            async with open_platform(config) as platform:
                one, two = MatchService(platform), MatchService(platform)
                first, second = await asyncio.gather(
                    one.start(room_id), two.start(room_id)
                )
                assert first == second
                state = await one.repo.get(first)
                assert state and state.turn is not None
                return first, state.turn

        game, seat = asyncio.run(start())
        assert client.get(path, headers=players[0]).json()["game_id"] == str(game)
        socket_path = f"/api/v1/games/{game}/ws"
        with client.websocket_connect(socket_path, headers=players[seat]) as socket:
            assert socket.receive_json()["events"][0]["event"] == "game_started"
            sync = socket.receive_json()
            assert sync["view"]["legal_moves"] == [{"suit": "Spades", "rank": "Ace"}]
            with client.websocket_connect(
                socket_path + "?after_sequence=2", headers=players[seat]
            ) as rejected:
                with pytest.raises(WebSocketDisconnect) as closed:
                    rejected.receive_json()
                assert closed.value.code == 4409
                assert closed.value.reason == "invalid_sequence"
            socket.send_json({"action": "ping"})
            assert socket.receive_json() == {"type": "pong"}
            request = {
                "action": "play_card",
                "card": sync["view"]["legal_moves"][0],
                "expected_version": sync["version"],
                "request_id": str(uuid4()),
            }
            socket.send_json(request)
            first = socket.receive_json()
            assert first["type"] == "ack"
            assert socket.receive_json()["events"][0]["event"] == "card_played"
            assert socket.receive_json()["type"] == "state_sync"
            socket.send_json(request)
            assert socket.receive_json() == first
        with client.websocket_connect(
            socket_path + "?after_sequence=1", headers=players[1 - seat]
        ) as socket:
            catchup = socket.receive_json()
            assert catchup["sequence"] == 2
            assert catchup["events"][0]["seat"] == seat
            sync = socket.receive_json()
            assert sync["version"] == 1
            assert len(sync["view"]["hand"]) == sync["view"]["card_counts"][1 - seat]


def test_deadlines_take_over_and_archive_only_once(settings):
    config = settings.model_copy(
        update={
            "room_start_seconds": 0,
            "turn_seconds": 0.001,
            "bot_turn_seconds": 0.001,
        }
    )
    with prepare_match(config) as client:
        tokens = [sign_in(client) for _ in range(2)]
        players = [headers(token) for token in tokens]
        old_path, room_id = ready_room(client, players, capacity=3)

        async def settle():
            async with open_platform(config) as platform:
                match = MatchService(platform)
                game = await match.start(room_id)
                for _ in range(1050):
                    await asyncio.sleep(0.002)
                    await match.tick()
                    state = await match.repo.get(game)
                    if state and state.status == "finished":
                        await asyncio.gather(
                            match.settle(game), MatchService(platform).settle(game)
                        )
                        return game
                raise AssertionError("Autoplay failed to finish a game")

        game = asyncio.run(settle())
        replay = client.get(f"/api/v1/games/{game}/replay", headers=players[0]).json()
        events = [event for batch in replay["events"] for event in batch["events"]]
        assert any(event["event"] == "seat_taken_over" for event in events)
        assert events[-1]["event"] == "game_finished"
        assert (
            client.get("/api/v1/matchmaking/status", headers=players[0]).json()[
                "status"
            ]
            == "idle"
        )
        outsider = headers(sign_in(client))
        assert (
            client.get(f"/api/v1/games/{game}/replay", headers=outsider).status_code
            == 404
        )
        assert profile(client, tokens[0])["mmr"] == 1200
        new_room = client.post(
            "/api/v1/rooms", json={"capacity": 2}, headers=players[0]
        )
        assert new_room.status_code == 201
        assert client.post(old_path + "/join", headers=outsider).status_code == 404
        assert (
            client.get("/api/v1/matchmaking/status", headers=players[0]).json()[
                "room_id"
            ]
            == new_room.json()["id"]
        )


def test_failed_settlement_is_retried_without_delaying_other_matches(
    settings, monkeypatch
):
    config = settings.model_copy(update={"room_start_seconds": 0, "match_minutes": 0})
    with prepare_match(config) as client:
        players = [headers(sign_in(client)) for _ in range(4)]
        _, first_room = ready_room(client, players[:2])
        _, second_room = ready_room(client, players[2:])

        async def settle():
            async with open_platform(config) as platform:
                match = MatchService(platform)
                first = await match.start(first_room)
                second = await match.start(second_room)
                assert first is not None and second is not None
                await match.on_deadline(first)
                await match.on_deadline(second)
                key = match.repo.game_key("index", "settlement")
                completed = await match.repo.now_ms() - 10_000
                await platform.redis.zadd(
                    key, {str(first): completed, str(second): completed + 1}
                )
                original = settlement.persist
                attempts = []

                async def flaky(platform, replay, *, finished_at):
                    attempts.append((replay.id, finished_at))
                    if replay.id == first and len(attempts) == 1:
                        raise RuntimeError("Temporary archive failure")
                    return await original(platform, replay, finished_at=finished_at)

                monkeypatch.setattr(settlement, "persist", flaky)
                await match.tick()
                assert [game_id for game_id, _ in attempts] == [first, second]
                assert (
                    await platform.redis.zscore(key, str(first))
                    > await match.repo.now_ms()
                )
                assert await platform.redis.zscore(key, str(second)) is None
                finished_at = attempts[0][1]
                season_window = (
                    finished_at - timedelta(seconds=1),
                    finished_at + timedelta(seconds=1),
                )
                assert (
                    await match.repo.season_settlement_status(*season_window)
                    == "pending"
                )
                await match.tick()
                assert len(attempts) == 2

                # Make the retry due without waiting for the backoff.
                await platform.redis.zadd(key, {str(first): await match.repo.now_ms()})
                await match.tick()
                assert attempts[0] == attempts[2]
                assert await platform.redis.zscore(key, str(first)) is None
                assert (
                    await match.repo.season_settlement_status(*season_window) == "clear"
                )
                return first, second

        first, second = asyncio.run(settle())
        assert (
            client.get(f"/api/v1/games/{first}/replay", headers=players[0]).status_code
            == 200
        )
        assert (
            client.get(f"/api/v1/games/{second}/replay", headers=players[2]).status_code
            == 200
        )


def test_established_socket_outlives_access_token_and_closes_on_logout(
    settings, monkeypatch
):
    config = settings.model_copy(update={"room_start_seconds": 0})
    with prepare_match(config) as client:
        players = [headers(sign_in(client)) for _ in range(2)]
        _, room_id = ready_room(client, players)

        async def start():
            async with open_platform(config) as platform:
                return await MatchService(platform).start(room_id)

        game = asyncio.run(start())
        path = f"/api/v1/games/{game}/ws"
        monkeypatch.setattr(matches_router, "monotonic", count(step=6).__next__)

        class ExpiredAccessClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(UTC) + timedelta(hours=1)

        with client.websocket_connect(path, headers=players[0]) as socket:
            assert socket.receive_json()["type"] == "events"
            assert socket.receive_json()["type"] == "state_sync"
            with monkeypatch.context() as expired:
                expired.setattr(jwt.api_jwt, "datetime", ExpiredAccessClock)
                assert (
                    client.get("/api/v1/auth/me", headers=players[0]).status_code == 401
                )
                socket.send_json({"action": "ping"})
                assert socket.receive_json() == {"type": "pong"}
            assert (
                client.post("/api/v1/auth/logout", headers=players[0]).status_code
                == 204
            )
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 4401

        with client.websocket_connect(path, headers=players[1]) as socket:
            assert socket.receive_json()["type"] == "events"
            assert socket.receive_json()["type"] == "state_sync"
            socket.send_bytes(b"binary")
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 1003
        with client.websocket_connect(path, headers=players[1]) as socket:
            assert socket.receive_json()["type"] == "events"
            assert socket.receive_json()["type"] == "state_sync"
            socket.send_text("x" * 8193)
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 1009


def test_browser_ticket_negotiates_subprotocol_and_cannot_be_replayed(settings):
    config = settings.model_copy(update={"room_start_seconds": 0})
    with prepare_match(config) as client:
        players = [headers(sign_in(client)) for _ in range(2)]
        stranger = headers(sign_in(client))
        _, room_id = ready_room(client, players)

        async def start():
            async with open_platform(config) as platform:
                return await MatchService(platform).start(room_id)

        game_id = asyncio.run(start())
        assert game_id is not None
        path = f"/api/v1/games/{game_id}"
        assert client.post(path + "/ws-ticket", headers=stranger).status_code == 404
        response = client.post(path + "/ws-ticket", headers=players[0], json={})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        protocols = ["donke.v1", "ticket." + response.json()["ticket"]]
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                path + "/ws",
                headers={"Origin": "http://elsewhere.example"},
                subprotocols=protocols,
            ),
        ):
            pass
        with client.websocket_connect(
            path + "/ws",
            headers={"Origin": "http://testserver"},
            subprotocols=protocols,
        ) as socket:
            assert socket.accepted_subprotocol == "donke.v1"
            assert socket.receive_json()["type"] == "events"
            assert socket.receive_json()["type"] == "state_sync"
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                path + "/ws",
                headers={"Origin": "http://testserver"},
                subprotocols=protocols,
            ),
        ):
            pass
