import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_online import client as client  # noqa: PLC0414
from test_online import headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.errors import AppError
from app.core.platform import open_platform
from app.main import create_app
from app.modules.admin.helpers import flag_specs, totp
from app.modules.admin.services.admin import AdminService

PASSWORD = "synthetic-console-admin"


def test_totp_matches_the_rfc_6238_vector_and_allows_one_step_of_drift():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # ASCII "12345678901234567890"
    assert totp.code_at(secret, 59 // 30) == "287082"
    assert totp.matching_step(secret, "287082", 59) == 1
    assert totp.matching_step(secret, "287082", 59 + 30) == 1
    assert totp.matching_step(secret, "287082", 59 + 90) is None
    fresh = totp.new_secret()
    assert len(fresh) == 32 and totp.provisioning_uri(fresh, "ops").startswith(
        "otpauth://totp/DonkE%20Admin%3Aops?secret="
    )


def test_flag_values_are_validated_against_the_allowlist():
    assert flag_specs.validate("ai_enabled", False) is False
    assert flag_specs.validate("ai_text_daily_calls", 10) == 10
    assert flag_specs.validate("maintenance_notice", "  Back soon  ") == "Back soon"
    for key, value in [
        ("ai_enabled", "no"),
        ("ai_text_daily_calls", True),
        ("ai_text_daily_calls", 6000),
        ("maintenance_notice", "x" * 201),
    ]:
        with pytest.raises(AppError) as invalid:
            flag_specs.validate(key, value)
        assert invalid.value.code == "invalid_flag_value"
    with pytest.raises(AppError):
        flag_specs.validate("secret_key", "x")


def test_admin_ui_is_served_separately_with_a_strict_policy():
    with TestClient(create_app()) as plain:
        page = plain.get("/admin/")
        assert page.status_code == 200 and "<title>DonkE Admin</title>" in page.text
        policy = page.headers["content-security-policy"]
        assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
        script = plain.get("/admin/assets/js/app.js")
        assert script.status_code == 200
        assert script.headers["x-content-type-options"] == "nosniff"
        assert plain.get("/admin/../app/main.py").status_code == 404
        assert "innerHTML" not in script.text


def admin_login(client, settings, role="admin"):
    username = f"ops-{uuid4().hex[:8]}"

    async def create():
        async with open_platform(settings) as platform:
            await AdminService(platform).create_account(
                username, PASSWORD, role, uuid4()
            )

    asyncio.run(create())
    login = client.post(
        "/api/v1/admin/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return username, {"X-CSRF-Token": login.json()["csrf_token"]}


@pytest.mark.integration
def test_console_players_flags_and_roles(client, settings):
    _, csrf = admin_login(client, settings)
    assert client.get("/api/v1/admin/dashboard").status_code == 200

    player_tokens = sign_in(client)
    player = profile(client, player_tokens)
    found = client.get("/api/v1/admin/players", params={"q": player["id"]}).json()
    assert [row["id"] for row in found] == [player["id"]]
    path = f"/api/v1/admin/players/{player['id']}"
    assert client.get(path).json()["coins"] == 0

    granted = client.post(
        f"{path}/coins", json={"amount": 50, "reason": "Support credit"}, headers=csrf
    )
    assert granted.json() == {"coins": 50}
    too_much = client.post(
        f"{path}/coins", json={"amount": -60, "reason": "Fix"}, headers=csrf
    )
    assert too_much.status_code == 409
    assert client.post(f"{path}/ban", json={"reason": "x"}).status_code == 422

    banned = client.post(f"{path}/ban", json={"reason": "Abuse"}, headers=csrf)
    assert banned.status_code == 200 and banned.json()["active"] is False
    assert (
        client.get("/api/v1/auth/me", headers=headers(player_tokens)).status_code == 401
    )
    client.post(f"{path}/unban", json={"reason": "Appeal"}, headers=csrf)
    assert client.get(path).json()["player"]["active"] is True

    notice = client.put(
        "/api/v1/admin/flags/maintenance_notice",
        json={"value": "Back at 6pm", "reason": "Deploy"},
        headers=csrf,
    )
    assert notice.status_code == 200, notice.text
    assert client.get("/api/v1/notice").json() == {"message": "Back at 6pm"}
    client.put(
        "/api/v1/admin/flags/maintenance_notice",
        json={"value": None, "reason": "Done"},
        headers=csrf,
    )
    assert client.get("/api/v1/notice").json() == {"message": ""}
    off = client.put(
        "/api/v1/admin/flags/ai_enabled",
        json={"value": False, "reason": "Cost"},
        headers=csrf,
    )
    assert off.json()["value"] is False
    assert (
        client.put(
            "/api/v1/admin/flags/nope", json={"value": 1, "reason": "x x"}, headers=csrf
        ).status_code
        == 404
    )
    client.put(
        "/api/v1/admin/flags/ai_enabled",
        json={"value": None, "reason": "Back"},
        headers=csrf,
    )

    audit = [entry["action"] for entry in client.get("/api/v1/admin/audit").json()]
    assert {"grant_coins", "ban_player", "unban_player", "flag_ai_enabled"} <= set(
        audit
    )

    with TestClient(client.app, base_url="https://testserver") as viewer_client:
        _, viewer_csrf = admin_login(viewer_client, settings, role="viewer")
        assert viewer_client.get("/api/v1/admin/players").status_code == 200
        forbidden = viewer_client.post(
            f"{path}/ban", json={"reason": "Abuse"}, headers=viewer_csrf
        )
        assert forbidden.status_code == 403
        assert viewer_client.get("/api/v1/admin/users").status_code == 403


@pytest.mark.integration
def test_totp_setup_then_sign_in_needs_a_fresh_code(client, settings):
    username, csrf = admin_login(client, settings)
    setup = client.post("/api/v1/admin/auth/totp/setup", headers=csrf).json()
    now = datetime.now(UTC).timestamp()
    wrong = client.post(
        "/api/v1/admin/auth/totp/confirm", json={"code": "000000"}, headers=csrf
    )
    if totp.code_at(setup["secret"], int(now // 30)) != "000000":
        assert wrong.status_code == 422
    code = totp.code_at(setup["secret"], int(now // 30))
    confirmed = client.post(
        "/api/v1/admin/auth/totp/confirm", json={"code": code}, headers=csrf
    )
    assert confirmed.json()["totp_enabled"] is True
    client.post("/api/v1/admin/auth/logout", headers=csrf)

    body = {"username": username, "password": PASSWORD}
    missing = client.post("/api/v1/admin/auth/login", json=body)
    assert (
        missing.status_code == 401
        and missing.json()["error"]["code"] == "totp_required"
    )
    fresh = totp.code_at(setup["secret"], int(datetime.now(UTC).timestamp() // 30))

    async def stored_secret():
        async with open_platform(settings) as platform, platform.sessions() as db:
            from sqlalchemy import select

            from app.modules.admin.models.admin_user import AdminUser

            return await db.scalar(
                select(AdminUser.totp_secret).where(AdminUser.username == username)
            )

    stored = asyncio.run(stored_secret())
    assert stored.startswith("v1:") and setup["secret"] not in stored
    signed = client.post("/api/v1/admin/auth/login", json={**body, "totp": fresh})
    assert signed.status_code == 200, signed.text
    assert (
        client.post(
            "/api/v1/admin/auth/login", json={**body, "totp": fresh}
        ).status_code
        == 401
    )


def test_totp_secrets_are_sealed_and_bound_to_their_account():
    from uuid import uuid4 as fresh

    from app.core.config import Settings
    from app.modules.admin.helpers import vault

    def online(**values):
        return Settings(
            _env_file=None,
            postgres_dsn="postgresql+asyncpg://u:p@localhost/d",
            redis_dsn="redis://localhost:6379/0",
            **values,
        )

    settings = online(auth_secret="x" * 40)
    owner, other = fresh(), fresh()
    secret = totp.new_secret()
    sealed = vault.seal(settings, owner, secret)
    assert sealed.startswith("v1:") and secret not in sealed and len(sealed) <= 128
    assert vault.seal(settings, owner, secret) != sealed  # fresh nonce each time
    assert vault.unseal(settings, owner, sealed) == secret
    for wrong in (
        lambda: vault.unseal(settings, other, sealed),  # copied to another admin
        lambda: vault.unseal(online(auth_secret="y" * 40), owner, sealed),
        lambda: vault.unseal(settings, owner, secret),  # legacy plain text
    ):
        with pytest.raises(AppError) as error:
            wrong()
        assert error.value.code == "totp_unreadable"
    dedicated = online(auth_secret="x" * 40, admin_totp_key="k" * 32)
    assert (
        vault.unseal(dedicated, owner, vault.seal(dedicated, owner, secret)) == secret
    )
    with pytest.raises(ValueError):
        online(auth_secret="x" * 40, admin_totp_key="short")


@pytest.mark.integration
def test_kill_switch_heals_when_the_cache_invalidation_fails(
    client, settings, monkeypatch
):
    from redis.exceptions import RedisError

    from app.modules.admin.services import flags

    _, csrf = admin_login(client, settings)

    async def read(*, drop_cache: bool = False):
        # Our own connection: the app's runs on the TestClient's loop.
        async with open_platform(settings) as platform:
            key = flags.cache_key(platform)
            ttl = await platform.redis.ttl(key)
            if drop_cache:
                await platform.redis.delete(key)  # what expiry does
            return (await flags.current(platform))["ai_enabled"], ttl

    assert asyncio.run(read())[0] is True  # now cached in Redis
    app_redis = client.app.state.platform.redis

    def broken_pipeline(*args, **kwargs):
        raise RedisError("down")

    monkeypatch.setattr(app_redis, "pipeline", broken_pipeline)
    off = client.put(
        "/api/v1/admin/flags/ai_enabled",
        json={"value": False, "reason": "Cost spike"},
        headers=csrf,
    )
    assert off.status_code == 200 and off.json()["value"] is False  # from Postgres
    monkeypatch.undo()
    stale, ttl = asyncio.run(read())
    assert stale is True and 0 < ttl <= flags.CACHE_SECONDS  # stale, but bounded
    assert asyncio.run(read(drop_cache=True))[0] is False  # healed after expiry

    on = client.put(
        "/api/v1/admin/flags/ai_enabled",
        json={"value": None, "reason": "Back"},
        headers=csrf,
    )
    assert on.json()["value"] is True
    assert asyncio.run(read())[0] is True  # normal path: no waiting for expiry


@pytest.mark.integration
def test_deactivating_an_admin_ends_sessions_for_good(client, settings):
    _, csrf = admin_login(client, settings)
    name = f"mod-{uuid4().hex[:8]}"

    async def moderator(action: str, cookie: str | None = None):
        async with open_platform(settings) as platform:
            service = AdminService(platform)
            if action == "create":
                await service.create_account(name, PASSWORD, "moderator", uuid4())
                return (await service.sign_in(name, PASSWORD, uuid4()))[1]
            if action == "sign_in":
                return (await service.sign_in(name, PASSWORD, uuid4()))[1]
            try:
                await service.current(cookie)
            except AppError:
                return False
            return True

    cookie = asyncio.run(moderator("create"))
    assert asyncio.run(moderator("check", cookie)) is True
    target = next(
        row["id"]
        for row in client.get("/api/v1/admin/users").json()
        if row["username"] == name
    )
    path = f"/api/v1/admin/users/{target}"
    client.put(path, json={"active": False, "reason": "Left team"}, headers=csrf)
    assert asyncio.run(moderator("check", cookie)) is False
    client.put(path, json={"active": True, "reason": "Rejoined"}, headers=csrf)
    # The old session stays dead; only a fresh sign-in works.
    assert asyncio.run(moderator("check", cookie)) is False
    fresh = asyncio.run(moderator("sign_in"))
    assert asyncio.run(moderator("check", fresh)) is True
