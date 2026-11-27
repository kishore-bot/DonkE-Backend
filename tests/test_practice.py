from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


def create_game(client, seats=4):
    response = client.post("/api/v1/practice", json={"seats": seats})
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    match = response.json()
    path = f"/api/v1/practice/{match['game_id']}"
    headers = {"Authorization": f"Bearer {match['access_token']}"}
    return match["view"], path, headers


def command(view):
    return {
        "request_id": str(uuid4()),
        "expected_version": view["version"],
        "card": view["legal_moves"][0],
    }


@pytest.mark.parametrize("seats", [2, 3, 4, 5])
def test_play_a_full_match(client, seats):
    view, path, headers = create_game(client, seats)
    assert len(view["card_counts"]) == seats
    assert len(view["hand"]) == view["card_counts"][0]
    while view["outcome"] is None:
        assert view["turn"] == 0
        response = client.post(f"{path}/plays", headers=headers, json=command(view))
        assert response.status_code == 200, response.text
        update = response.json()
        assert update["events"][0]["event"] == "card_played"
        assert update["events"][0]["seat"] == 0
        assert update["view"]["version"] > view["version"]
        view = update["view"]
        assert len(view["hand"]) == view["card_counts"][0]
        if view["outcome"] is not None:
            assert update["events"][-1]["outcome"] == view["outcome"]
    assert view["turn"] is None
    assert view["legal_moves"] == []
    if view["outcome"]["reason"] == "donkey":
        donkey = view["outcome"]["seat"]
        assert [i for i, count in enumerate(view["card_counts"]) if count] == [donkey]
    assert client.get(path, headers=headers).json() == {"view": view, "events": []}


def test_commands_are_idempotent_and_version_checked(client):
    view, path, headers = create_game(client)
    play = command(view)
    first = client.post(f"{path}/plays", headers=headers, json=play)
    assert first.status_code == 200
    repeat = client.post(f"{path}/plays", headers=headers, json=play)
    assert repeat.json() == first.json()
    stale = client.post(
        f"{path}/plays", headers=headers, json={**play, "request_id": str(uuid4())}
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_version"
    reused = client.post(
        f"{path}/plays",
        headers=headers,
        json={**play, "expected_version": view["version"] + 1},
    )
    assert reused.json()["error"]["code"] == "request_id_reused"
    assert client.get(path, headers=headers).json()["view"] == first.json()["view"]


def test_concurrent_commands_cannot_commit_the_same_version(client):
    view, path, headers = create_game(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(
            lambda play: client.post(f"{path}/plays", headers=headers, json=play),
            [command(view), command(view)],
        )
    assert sorted([first.status_code, second.status_code]) == [200, 409]


def test_match_access_and_validation(client):
    view, path, headers = create_game(client)
    _, _, other_headers = create_game(client)
    assert client.get(path).status_code == 401
    assert client.get(path, headers=other_headers).status_code == 404
    assert client.post("/api/v1/practice", json={"seats": True}).status_code == 422
    assert client.post("/api/v1/practice", json={"seats": 6}).status_code == 422
    illegal_card = next(
        {"suit": suit, "rank": rank}
        for suit in ("Spades", "Clubs", "Hearts", "Diamonds")
        for rank in ("Two", "Three", "Four", "Five", "Six", "Seven", "Eight")
        if {"suit": suit, "rank": rank} not in view["legal_moves"]
    )
    result = client.post(
        f"{path}/plays", headers=headers, json={**command(view), "card": illegal_card}
    )
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "illegal_card"
    assert client.get(path, headers=headers).json()["view"] == view


def test_expired_match_capacity_can_be_reused(monkeypatch):
    from app.modules.game.repositories import practice

    now = 0.0
    monkeypatch.setattr(practice, "monotonic", lambda: now)
    settings = Settings(practice_max_sessions=1, practice_session_ttl_seconds=1)
    with TestClient(create_app(settings)) as client:
        _, path, headers = create_game(client)
        assert client.post("/api/v1/practice", json={}).status_code == 503
        now = 1.0
        assert client.get(path, headers=headers).status_code == 404
        create_game(client)


def test_health_and_openapi(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/v1/practice/{game_id}/plays"]["post"]["security"] == [
        {"HTTPBearer": []}
    ]
    assert "PlayerView" in schema["components"]["schemas"]
