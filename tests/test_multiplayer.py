import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_online import TestGoogle, headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.main import create_app
from app.modules.matches.service import MatchService

pytestmark = pytest.mark.integration


def prepare_match(config):
    client = TestClient(create_app(config, TestGoogle()))
    return client


def ready_room(client, auth):
    room = client.post("/api/v1/rooms", json={"capacity": 2}, headers=auth[0]).json()
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
        _, room_id = ready_room(client, players)

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
