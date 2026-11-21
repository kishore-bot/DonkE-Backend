import asyncio
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from test_online import settings as settings  # noqa: PLC0414

from app.core.config import Settings
from app.core.errors import AppError
from app.core.platform import SCHEMA_HEAD, Platform, open_platform
from app.modules.lobby.repository import LobbyRepository
from app.modules.lobby.service import LobbyService
from app.modules.matches.service import MatchService
from app.modules.matches.settlement import read_replay
from app.modules.progression.service import ProgressionService
from scripts.demo_smoke import SmokeFailure, websocket_base
from scripts.seed_demo import (
    DEMO_SUBJECTS,
    SEEDS,
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
        redis = AsyncMock()
        platform = Platform(Settings(_env_file=None), engine, MagicMock(), redis)
        with pytest.raises(AppError) as captured:
            await platform.ready()
        assert captured.value.code == "schema_mismatch"
        assert captured.value.status == 503
        redis.ping.assert_not_awaited()

    asyncio.run(check())


def test_demo_tokens_require_loopback_or_encryption():
    assert websocket_base("https://dev.example.com") == "wss://dev.example.com"
    assert websocket_base("http://127.0.0.1:8000/") == "ws://127.0.0.1:8000"
    with pytest.raises(SmokeFailure, match="Use HTTPS"):
        websocket_base("http://dev.example.com")


@pytest.mark.integration
def test_demo_seed_is_guarded_and_idempotent(settings, tmp_path):
    async def check():
        async with open_platform(settings) as platform:
            with pytest.raises(AppError) as captured:
                await seed(platform)
            assert captured.value.code == "demo_disabled"

        config = settings.model_copy(update={"demo_mode": True})
        async with open_platform(config) as platform:
            first = await seed(platform)
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


@pytest.mark.integration
def test_missing_game_releases_all_room_reservations(settings):
    async def check():
        config = settings.model_copy(
            update={"demo_mode": True, "room_start_seconds": 0}
        )
        async with open_platform(config) as platform:
            lobby = LobbyService(LobbyRepository(platform.redis, config))
            matches = MatchService(platform)
            host, guest = await seed(platform)
            room = await lobby.create_room(host, 2)
            await lobby.room("join_room", guest, room.id)
            for player in host, guest:
                await lobby.room("ready", player, room.id, ready=True)
            game = await matches.start(room.id)
            assert game is not None
            assert (await lobby.queue_status(guest)).room_id == room.id

            await platform.redis.delete(matches.repo.game_key("state", game))
            assert (await lobby.queue_status(host)).status == "idle"
            assert (await lobby.queue_status(guest)).status == "idle"
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
