import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.platform import open_platform
from app.main import create_app
from app.modules.admin.service import AdminService
from app.modules.identity.schemas import Profile
from app.modules.lobby.repository import LobbyRepository
from app.modules.lobby.service import LobbyService, queue_for
from app.workers.matchmaking import match_once

pytestmark = pytest.mark.integration


class TestGoogle:
    __test__ = False

    async def verify(self, token):
        return token


@pytest.fixture
def settings():
    postgres, redis = os.getenv("TEST_POSTGRES_DSN"), os.getenv("TEST_REDIS_DSN")
    if not postgres or not redis:
        pytest.skip("Set TEST_POSTGRES_DSN and TEST_REDIS_DSN to disposable stores")
    return Settings(
        postgres_dsn=postgres,
        redis_dsn=redis,
        auth_secret="synthetic-test-key-with-at-least-32-bytes",
        redis_prefix=f"test-{uuid4().hex}",
        bot_fill_seconds=0,
        # Most tests check theft detection; the retry window has its own test.
        refresh_reuse_grace_seconds=0,
    )


@pytest.fixture
def client(settings):
    with TestClient(
        create_app(settings, TestGoogle()), base_url="https://testserver"
    ) as client:
        yield client


def sign_in(client, subject=None):
    response = client.post(
        "/api/v1/auth/google", json={"id_token": subject or uuid4().hex}
    )
    assert response.status_code == 200, response.text
    return response.json()


def headers(tokens):
    return {"Authorization": "Bearer " + tokens["access_token"]}


def profile(client, tokens):
    response = client.get("/api/v1/auth/me", headers=headers(tokens))
    assert response.status_code == 200, response.text
    return response.json()


def test_identity_rotation_replay_and_independent_families(client):
    assert client.get("/ready").status_code == 200
    subject = uuid4().hex
    original, second_login = sign_in(client, subject), sign_in(client, subject)
    assert profile(client, original)["id"] == profile(client, second_login)["id"]
    updated = client.patch(
        "/api/v1/auth/me", json={"language": "ta"}, headers=headers(original)
    )
    assert updated.json()["language"] == "ta"

    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
    )
    assert response.status_code == 200
    refreshed = response.json()
    assert refreshed["refresh_token"] != original["refresh_token"]

    replay = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
    )
    assert replay.status_code == 401
    assert client.get("/api/v1/auth/me", headers=headers(refreshed)).status_code == 401
    assert profile(client, second_login)["language"] == "ta"
    assert (
        client.post("/api/v1/auth/logout", headers=headers(second_login)).status_code
        == 204
    )
    assert (
        client.get("/api/v1/auth/me", headers=headers(second_login)).status_code == 401
    )


def test_concurrent_refresh_rotates_at_most_once(client):
    original = sign_in(client)
    payload = {"refresh_token": original["refresh_token"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda _: client.post("/api/v1/auth/refresh", json=payload), range(2)
            )
        )
    assert sorted(item.status_code for item in outcomes) == [200, 401]
    winner = next(item.json() for item in outcomes if item.status_code == 200)
    assert client.get("/api/v1/auth/me", headers=headers(winner)).status_code == 401


def test_room_admission_ready_kick_and_host_transfer(client):
    host, guest, visitor = (headers(sign_in(client)) for _ in range(3))
    created = client.post("/api/v1/rooms", json={"capacity": 2}, headers=host)
    assert created.status_code == 201, created.text
    room = created.json()
    path = f"/api/v1/rooms/{room['id']}"
    assert client.get(path, headers=guest).status_code == 404
    assert client.post(f"{path}/join", headers=guest).status_code == 200
    assert client.post(f"{path}/join", headers=guest).status_code == 200
    assert (
        client.post(f"{path}/join", headers=visitor).json()["error"]["code"]
        == "room_full"
    )
    assert (
        client.post("/api/v1/matchmaking/join", json={}, headers=guest).status_code
        == 409
    )
    assert (
        client.delete(f"{path}/members/{room['host_id']}", headers=guest).status_code
        == 403
    )
    for player in (host, guest):
        ready = client.put(f"{path}/ready", json={"ready": True}, headers=player)
    assert ready.json()["status"] == "ready"
    guest_id = ready.json()["seats"][1]["player_id"]
    assert client.delete(f"{path}/members/{guest_id}", headers=host).status_code == 200
    assert client.get(path, headers=guest).status_code == 404
    assert client.post(f"{path}/join", headers=guest).status_code == 200
    assert client.post(f"{path}/leave", headers=host).status_code == 204
    assert client.post(f"{path}/leave", headers=host).status_code == 204
    assert client.get(path, headers=guest).json()["host_id"] == guest_id
    assert client.post(f"{path}/leave", headers=guest).status_code == 204
    assert client.get(path, headers=guest).status_code == 404


def test_queue_and_room_creation_have_one_winner(client):
    player = headers(sign_in(client))
    paths = ("/api/v1/rooms", "/api/v1/matchmaking/join")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(lambda path: client.post(path, json={}, headers=player), paths)
        )
    assert outcomes[0].status_code in {201, 409}
    assert outcomes[1].status_code in {200, 409}
    assert [item.status_code for item in outcomes].count(409) == 1


def test_worker_publishes_private_ranked_lobby_with_bots(client, settings):
    players = [headers(sign_in(client)) for _ in range(2)]
    visitor = headers(sign_in(client))
    for player in players:
        queued = client.post(
            "/api/v1/matchmaking/join", json={"mode": "ranked"}, headers=player
        )
        assert queued.json()["status"] == "queued"

    async def run_worker():
        async with open_platform(settings) as platform:
            return await match_once(
                LobbyService(LobbyRepository(platform.redis, settings))
            )

    assert asyncio.run(run_worker()) == 1
    first, second = (
        client.get("/api/v1/matchmaking/status", headers=player).json()
        for player in players
    )
    assert first == second
    assert first["status"] == "matched"
    path = f"/api/v1/rooms/{first['room_id']}"
    room = client.get(path, headers=players[0]).json()
    assert room["status"] == "ready"
    assert room["mode"] == "ranked"
    assert sum(seat["bot"] for seat in room["seats"]) == 2
    assert client.post(f"{path}/join", headers=visitor).status_code == 404
    assert client.post(f"{path}/leave", headers=players[0]).status_code == 204
    assert (
        client.get("/api/v1/matchmaking/status", headers=players[1]).json()["status"]
        == "idle"
    )


def sample():
    return Profile(id=uuid4(), display_name="Test player", language="ml", mmr=1200)


def test_cancellation_and_rollback_preserve_new_membership_and_fifo(settings):
    async def scenario():
        async with open_platform(settings) as platform:
            lobby = LobbyService(LobbyRepository(platform.redis, settings))
            first, second = sample(), sample()
            timestamp = (await lobby.join_queue(first, "classic")).enqueued_at_ms
            await lobby.join_queue(second, "classic")
            claim = await lobby.claim("classic", "classic")
            assert claim is not None
            assert (await lobby.queue_status(first)).status == "matching"
            assert await lobby.finalize(replace(claim, owner=uuid4())) is None
            await lobby.rollback(claim)
            assert (await lobby.queue_status(first)).enqueued_at_ms == timestamp
            claim = await lobby.claim("classic", "classic")
            assert claim is not None
            assert (await lobby.cancel_queue(second)).status == "idle"
            other_room = await lobby.create_room(second, 4)
            assert await lobby.finalize(claim) is None
            assert (await lobby.queue_status(first)).enqueued_at_ms == timestamp
            assert (await lobby.queue_status(second)).room_id == other_room.id
            assert await lobby.recover() == 0

    asyncio.run(scenario())


def test_expired_claim_recovers_and_cannot_overwrite_new_owner(settings):
    settings = settings.model_copy(update={"claim_lease_seconds": 0.08})

    async def scenario():
        async with open_platform(settings) as platform:
            lobby = LobbyService(LobbyRepository(platform.redis, settings))
            player = sample()
            await lobby.join_queue(player, "classic")
            claim = await lobby.claim("classic", "classic")
            assert claim is not None
            await asyncio.sleep(0.12)
            assert await lobby.finalize(claim) is None
            assert await lobby.recover() == 1
            assert (await lobby.queue_status(player)).status == "queued"
            second = await lobby.claim("classic", "classic")
            assert second is not None
            await lobby.rollback(claim)
            assert (await lobby.finalize(second)) is not None

    asyncio.run(scenario())


def test_ranked_bands_and_bot_fill_window(settings):
    settings = settings.model_copy(update={"bot_fill_seconds": 1})

    async def scenario():
        async with open_platform(settings) as platform:
            lobby = LobbyService(LobbyRepository(platform.redis, settings))
            low = [sample() for _ in range(4)]
            high = sample().model_copy(update={"mmr": 4200})
            await lobby.join_queue(high, "ranked")
            assert await lobby.claim("ranked", queue_for("ranked", high.mmr)) is None
            for player in low:
                await lobby.join_queue(player, "ranked")
            claim = await lobby.claim("ranked", queue_for("ranked", 1200))
            assert claim is not None
            room = await lobby.finalize(claim)
            assert room is not None
            assert all(not seat.bot for seat in room.seats)
            assert {seat.player_id for seat in room.seats} == {
                player.id for player in low
            }
            await asyncio.sleep(1.05)
            claim = await lobby.claim("ranked", queue_for("ranked", high.mmr))
            assert claim is not None
            room = await lobby.finalize(claim)
            assert room is not None
            assert sum(seat.bot for seat in room.seats) == 3

    asyncio.run(scenario())


def test_admin_cookie_csrf_role_and_audit(client, settings):
    async def create_accounts():
        async with open_platform(settings) as platform:
            service = AdminService(platform)
            admin = await service.create_account(
                f"admin-{uuid4().hex[:10]}", "test-only-password", "admin", uuid4()
            )
            viewer = await service.create_account(
                f"viewer-{uuid4().hex[:10]}", "test-only-password", "viewer", uuid4()
            )
            return admin, viewer

    admin, viewer = asyncio.run(create_accounts())
    path = "/api/v1/admin/auth"
    assert (
        client.post(
            f"{path}/login", json={"username": viewer.username, "password": "wrong"}
        ).status_code
        == 401
    )
    result = client.post(
        f"{path}/login",
        json={"username": viewer.username, "password": "test-only-password"},
    )
    assert result.status_code == 200, result.text
    assert client.get("/api/v1/admin/audit").status_code == 403
    assert client.post(f"{path}/logout").json()["error"]["code"] == "csrf_required"
    csrf = {"X-CSRF-Token": result.json()["csrf_token"]}
    assert client.post(f"{path}/logout", headers=csrf).status_code == 204
    assert client.get(f"{path}/me").status_code == 401
    request_id = uuid4()
    result = client.post(
        f"{path}/login",
        json={"username": admin.username, "password": "test-only-password"},
        headers={"X-Request-ID": str(request_id)},
    )
    assert result.status_code == 200
    cookie = result.headers["set-cookie"].lower()
    assert cookie.startswith("__host-donke-admin=")
    assert all(flag in cookie for flag in ("secure", "httponly", "samesite=strict"))
    audit = client.get("/api/v1/admin/audit")
    assert audit.status_code == 200
    assert any(entry["request_id"] == str(request_id) for entry in audit.json())


@pytest.mark.parametrize(
    ("key", "dsn"),
    [
        ("redis_dsn", "redis://127.0.0.1:1/0"),
        ("postgres_dsn", "postgresql+asyncpg://donke@127.0.0.1:1/postgres"),
    ],
)
def test_ready_reports_unavailable_store_without_affecting_liveness(settings, key, dsn):
    config = Settings.model_validate({**settings.model_dump(), key: dsn})
    with TestClient(create_app(config)) as client:
        assert client.get("/healthz").status_code == 200
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "store_unavailable"


def test_a_lost_refresh_response_can_be_retried_but_theft_still_revokes(settings):
    from datetime import UTC, datetime, timedelta

    from app.modules.identity import service as identity_service

    config = settings.model_copy(update={"refresh_reuse_grace_seconds": 20})
    with TestClient(
        create_app(config, TestGoogle()), base_url="https://testserver"
    ) as client:
        original = sign_in(client)
        payload = {"refresh_token": original["refresh_token"]}
        first = client.post("/api/v1/auth/refresh", json=payload)
        # The app never saw `first` (network dropped) and retries.
        retry = client.post("/api/v1/auth/refresh", json=payload)
        assert first.status_code == retry.status_code == 200
        assert (
            client.get("/api/v1/auth/me", headers=headers(retry.json())).status_code
            == 200
        )

        later = datetime.now(UTC) + timedelta(seconds=21)

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return later

        identity_service.datetime = Later
        try:
            stolen = client.post("/api/v1/auth/refresh", json=payload)
        finally:
            identity_service.datetime = datetime
        assert stolen.status_code == 401
        assert (
            client.get("/api/v1/auth/me", headers=headers(retry.json())).status_code
            == 401
        )


def test_empty_secrets_are_rejected_or_treated_as_unset():
    online = {
        "postgres_dsn": "postgresql+asyncpg://u:p@localhost/d",
        "redis_dsn": "redis://localhost:6379/0",
    }
    with pytest.raises(ValueError):
        Settings(_env_file=None, auth_secret="", **online)
    assert (
        Settings(
            _env_file=None, auth_secret="x" * 32, admin_totp_key="", **online
        ).admin_totp_key
        is None
    )
    with pytest.raises(ValueError):
        Settings(_env_file=None, auth_secret="x" * 32, admin_totp_key="short", **online)
