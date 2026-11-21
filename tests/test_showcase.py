import asyncio
import os
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, select, text
from test_online import settings as settings  # noqa: PLC0414

from app.core.config import Settings
from app.core.errors import AppError
from app.core.platform import SCHEMA_HEAD, Platform, open_platform
from app.core.schema import has_required_schema
from app.modules.identity.service import IdentityService
from app.modules.lobby.repository import LobbyRepository
from app.modules.lobby.service import LobbyService
from app.modules.matches.service import MatchService
from app.modules.matches.settlement import read_replay
from app.modules.progression.models import Season
from app.modules.progression.service import ProgressionService
from app.workers import matchmaking
from scripts.demo_smoke import SmokeFailure, cleanup_room, websocket_base
from scripts.seed_demo import (
    DEMO_SUBJECTS,
    SEEDS,
    DemoSession,
    DemoSessions,
    replay_id,
    seed,
    sessions,
    write_sessions,
)


def test_schema_head_and_readiness_reject_outdated_database():
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    migrations = ScriptDirectory.from_config(config)
    assert migrations.get_heads() == [SCHEMA_HEAD]

    async def check():
        engine = MagicMock()
        connection = engine.connect.return_value.__aenter__.return_value
        connection.scalars = AsyncMock(return_value=["20261120_platform"])
        connection.run_sync = AsyncMock(return_value=False)
        redis = AsyncMock()
        platform = Platform(Settings(_env_file=None), engine, MagicMock(), redis)
        with pytest.raises(AppError) as captured:
            await platform.ready()
        assert captured.value.code == "schema_mismatch"
        assert captured.value.status == 503
        redis.ping.assert_not_awaited()
        connection.scalars.return_value = ["20261121_future"]
        connection.run_sync.return_value = True
        await platform.ready()
        redis.ping.assert_awaited_once()

    asyncio.run(check())


@pytest.mark.integration
def test_expanded_schema_keeps_existing_release_ready(settings):
    async def check():
        async with open_platform(settings) as platform, platform.engine.connect() as db:
            transaction = await db.begin()
            try:
                await db.execute(
                    text("ALTER TABLE rule_embeddings ADD COLUMN details text")
                )
                assert await db.run_sync(has_required_schema)
                await db.execute(
                    text(
                        "ALTER TABLE rule_embeddings ADD COLUMN required integer NOT NULL DEFAULT 0"
                    )
                )
                assert await db.run_sync(has_required_schema)
                await db.execute(
                    text(
                        "ALTER TABLE rule_embeddings ALTER COLUMN required DROP DEFAULT"
                    )
                )
                assert not await db.run_sync(has_required_schema)
                await db.execute(
                    text("ALTER TABLE rule_embeddings DROP COLUMN required")
                )
                await db.execute(
                    text("ALTER TABLE rule_embeddings DROP COLUMN vector_json")
                )
                assert not await db.run_sync(has_required_schema)
            finally:
                await transaction.rollback()

    asyncio.run(check())


@pytest.fixture
def demo_settings(settings):
    demo = settings.model_copy(update={"demo_mode": True})

    async def existing_seasons():
        async with open_platform(demo) as platform, platform.sessions() as db:
            return list(await db.scalars(select(Season.id)))

    async def cleanup(existing):
        async with open_platform(demo) as platform, platform.sessions.begin() as db:
            await db.execute(
                delete(Season).where(
                    Season.theme == "Monsoon Demo", Season.id.not_in(existing)
                )
            )

    existing = asyncio.run(existing_seasons())
    try:
        yield demo
    finally:
        asyncio.run(cleanup(existing))


def test_demo_tokens_require_loopback_or_encryption():
    assert websocket_base("https://dev.example.com") == "wss://dev.example.com"
    assert websocket_base("http://127.0.0.1:8000/") == "ws://127.0.0.1:8000"
    with pytest.raises(SmokeFailure, match="Use HTTPS"):
        websocket_base("http://dev.example.com")


def test_smoke_cleanup_releases_both_waiting_seats():
    async def check():
        http = AsyncMock()
        http.post.return_value.status_code = 204
        room = uuid4()
        players = (
            DemoSession(player_id=uuid4(), access_token="synthetic-host"),
            DemoSession(player_id=uuid4(), access_token="synthetic-guest"),
        )
        await cleanup_room(http, "ws://127.0.0.1", room, players)
        assert http.post.await_count == 2
        assert all(
            call.args == (f"/api/v1/rooms/{room}/leave",)
            for call in http.post.await_args_list
        )

    asyncio.run(check())


@pytest.mark.integration
def test_demo_seed_is_guarded_and_idempotent(settings, demo_settings, tmp_path):
    async def check():
        async with open_platform(settings) as platform:
            with pytest.raises(AppError) as captured:
                await seed(platform)
            assert captured.value.code == "demo_disabled"

        async with open_platform(demo_settings) as platform:
            async with platform.sessions.begin() as db:
                db.add(
                    Season(
                        theme="Monsoon Demo",
                        starts_at=datetime(2010, 1, 1, tzinfo=UTC),
                        ends_at=datetime(2010, 2, 1, tzinfo=UTC),
                        closed_at=datetime(2010, 2, 2, tzinfo=UTC),
                    )
                )
            first = await seed(platform)
            async with platform.sessions() as db:
                now = datetime.now(UTC)
                assert await db.scalar(
                    select(Season.id).where(
                        Season.starts_at <= now, Season.ends_at > now
                    )
                )
            wallet = ProgressionService(platform)
            first_coins = [await wallet.balance(profile.id) for profile in first]
            assert all(total >= len(SEEDS) * 10 for total in first_coins)
            second = await seed(platform)
            assert first == second
            assert [
                await wallet.balance(profile.id) for profile in second
            ] == first_coins
            assert [profile.display_name for profile in first] == [
                row[1] for row in DEMO_SUBJECTS
            ]
            replay = await read_replay(platform, replay_id(SEEDS[0]), first[0].id)
            assert replay.events[-1].events[-1]["event"] == "game_finished"
            data = await sessions(platform, first)
            private = tmp_path / "demo-sessions.json"
            write_sessions(private, data)
            assert stat.S_IMODE(private.stat().st_mode) == 0o600
            assert DemoSessions.model_validate_json(private.read_bytes()) == data
            with pytest.raises(FileExistsError):
                write_sessions(private, data)

    asyncio.run(check())


def test_matchmaking_survives_store_disconnects(monkeypatch):
    platform = MagicMock()
    platform.settings = Settings(_env_file=None, matchmaking_poll_seconds=0.001)
    poll = AsyncMock(side_effect=[ConnectionRefusedError, 0])
    prune = AsyncMock(side_effect=TimeoutError)
    monkeypatch.setattr(matchmaking, "match_once", poll)
    monkeypatch.setattr(matchmaking, "prune_sessions", prune)
    monkeypatch.setattr(matchmaking, "analysis_tick", AsyncMock(return_value=0))

    async def check():
        stop = asyncio.Event()

        async def tick():
            stop.set()

        worker = AsyncMock()
        worker.tick = tick
        monkeypatch.setattr(matchmaking, "MatchService", lambda _: worker)
        await asyncio.wait_for(matchmaking.run(platform, stop), timeout=1)

    asyncio.run(check())
    assert poll.await_count == 2
    prune.assert_awaited_once()


@pytest.mark.integration
def test_missing_game_releases_all_room_reservations(settings):
    async def check():
        config = settings.model_copy(update={"room_start_seconds": 0})
        async with open_platform(config) as platform:
            lobby = LobbyService(LobbyRepository(platform.redis, config))
            matches = MatchService(platform)
            identity = IdentityService(platform)
            users = [await identity.sign_in(uuid4().hex) for _ in range(2)]
            host, guest = [
                (await identity.authenticate(user.access_token)).profile
                for user in users
            ]
            room = await lobby.create_room(host, 2)
            await lobby.room("join_room", guest, room.id)
            for player in host, guest:
                await lobby.room("ready", player, room.id, ready=True)
            game = await matches.start(room.id)
            assert game is not None
            assert (await lobby.queue_status(guest)).room_id == room.id
            pending = matches.repo.game_key("index", "settlement")
            deferred = matches.repo.game_key("index", "deferred_finishes")
            await platform.redis.zadd(pending, {str(game): 1})
            await platform.redis.zadd(deferred, {str(game): 1})

            await platform.redis.delete(matches.repo.game_key("state", game))
            assert (await lobby.queue_status(host)).status == "idle"
            assert (await lobby.queue_status(guest)).status == "idle"
            for key in (matches.repo.game_key("index", "turns"), pending, deferred):
                assert await platform.redis.zscore(key, str(game)) is None
            replacement = await lobby.create_room(guest, 2)
            assert replacement.id != room.id
            await lobby.leave_room(guest, replacement.id)

    asyncio.run(check())


@pytest.mark.parametrize("migration_code", [0, 7])
def test_podman_launcher_pins_provider_and_waits_for_migrations(
    tmp_path, migration_code
):
    log = tmp_path / "commands"
    provider = tmp_path / "podman-compose"
    provider.write_text(
        '#!/bin/sh\nprintf "provider %s\n" "$*" >> "$PODMAN_TEST_LOG"\n',
        encoding="utf-8",
    )
    podman = tmp_path / "podman"
    podman.write_text(
        '#!/bin/sh\nprintf "podman %s %s\n" "$PODMAN_COMPOSE_PROVIDER" "$*" >> "$PODMAN_TEST_LOG"\n'
        'case " $* " in *" run --rm migrate "*) exit "$PODMAN_TEST_MIGRATION_CODE";; esac\n',
        encoding="utf-8",
    )
    for command in (podman, provider):
        command.chmod(0o700)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "PODMAN_COMPOSE_PROVIDER": "unexpected-provider",
        "PODMAN_TEST_LOG": str(log),
        "PODMAN_TEST_MIGRATION_CODE": str(migration_code),
    }
    launcher = Path(__file__).resolve().parents[1] / "scripts/podman-dev.sh"
    result = subprocess.run(["bash", str(launcher), "up"], env=env, check=False)
    assert result.returncode == migration_code
    commands = log.read_text().splitlines()
    assert commands[0] == "provider --file compose.yml config"
    assert all(line.startswith(f"podman {provider} ") for line in commands[1:])
    stores = next(
        i for i, line in enumerate(commands) if line.endswith("up -d postgres redis")
    )
    migration = next(
        i for i, line in enumerate(commands) if line.endswith("run --rm migrate")
    )
    assert stores < migration
    assert any("pg_isready" in line for line in commands[stores:migration])
    assert any("redis-cli ping" in line for line in commands[stores:migration])
    assert any(
        line.endswith("up -d app matchmaking voice") for line in commands[migration:]
    ) == (migration_code == 0)
