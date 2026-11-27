import asyncio
import json
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from donke_engine import OnlineGame
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.admin import service as admin
from app.modules.ai import voice
from app.modules.game import service as practice
from app.modules.game.repository import PracticeRepository
from app.modules.game.schemas import PlayRequest
from app.modules.matches import socket_tickets
from app.modules.matches.schemas import GameSeat, MatchState
from app.modules.matches.service import MatchService


def test_practice_reserves_capacity_and_prunes_idle_clients(monkeypatch):
    repository = PracticeRepository()
    sessions = practice.PracticeService(
        repository, Settings(_env_file=None, practice_sessions_per_client=1)
    )
    repository.created["old-client"] = deque([0])
    monkeypatch.setattr(practice, "monotonic", lambda: 120.0)
    started, finish = Event(), Event()
    real_game = practice.PracticeGame

    def create(*args, **kwargs):
        started.set()
        assert finish.wait(5)
        return real_game(*args, **kwargs)

    monkeypatch.setattr(practice, "PracticeGame", create)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(sessions.create, 2, "easy", "player")
        try:
            assert started.wait(5)
            with pytest.raises(AppError) as rejected:
                sessions.create(2, "easy", "player")
            assert rejected.value.code == "practice_limit"
            assert "old-client" not in repository.created
        finally:
            finish.set()
        first.result(timeout=5)
    assert not repository.creating
    assert len(repository.sessions) == 1


def test_practice_releases_reservation_if_creation_fails(monkeypatch):
    repository = PracticeRepository()
    sessions = practice.PracticeService(
        repository, Settings(_env_file=None, practice_sessions_per_client=1)
    )

    def fail(*args, **kwargs):
        raise RuntimeError("engine failed")

    with monkeypatch.context() as patch:
        patch.setattr(practice, "PracticeGame", fail)
        with pytest.raises(RuntimeError, match="engine failed"):
            sessions.create(2, "easy", "player")
    assert not repository.creating
    assert sessions.create(2, "easy", "player")


def test_browser_ticket_is_origin_and_match_bound_and_single_use(monkeypatch):
    async def check():
        origin = "https://play.example"
        principal = SimpleNamespace(
            profile=SimpleNamespace(id=uuid4()), session_id=uuid4()
        )
        active_session = AsyncMock(return_value=principal)
        storage = {}

        async def store(key, value, *, ex):
            assert ex == socket_tickets.TICKET_TTL_SECONDS
            storage[key] = value

        async def consume(key):
            return storage.pop(key, None)

        platform = SimpleNamespace(
            settings=SimpleNamespace(redis_prefix="test", public_base_url=origin),
            redis=SimpleNamespace(set=store, getdel=consume),
        )
        monkeypatch.setattr(
            socket_tickets,
            "IdentityService",
            lambda _: SimpleNamespace(active_session=active_session),
        )
        game = uuid4()
        ticket = await socket_tickets.issue(platform, game, principal)
        protocols = [socket_tickets.PROTOCOL, "ticket." + ticket]
        assert ticket not in next(iter(storage))
        for match, origins in [(game, ["https://wrong.example"]), (uuid4(), [origin])]:
            with pytest.raises(AppError) as rejected:
                await socket_tickets.redeem(platform, match, protocols, origins, origin)
            assert rejected.value.status == 401
        assert (
            await socket_tickets.redeem(platform, game, protocols, [origin], origin)
            is principal
        )
        active_session.assert_awaited_once_with(
            principal.profile.id, principal.session_id
        )
        with pytest.raises(AppError) as replayed:
            await socket_tickets.redeem(platform, game, protocols, [origin], origin)
        assert replayed.value.status == 401

    asyncio.run(check())


def test_commentary_disable_pauses_queued_voice_jobs(monkeypatch):
    async def check():
        platform = SimpleNamespace(
            redis=SimpleNamespace(register_script=lambda _: None)
        )
        gateway = SimpleNamespace(platform=platform, provider=object())
        monkeypatch.setattr(
            voice.flags,
            "current",
            AsyncMock(return_value={"ai_enabled": True, "commentary_enabled": False}),
        )
        worker = voice.Voice(gateway)
        enqueue = AsyncMock()
        monkeypatch.setattr(worker, "execute", enqueue)
        assert not await voice.enabled(gateway)
        assert not await worker.tick()
        enqueue.assert_not_awaited()

    asyncio.run(check())


def test_console_account_failure_propagates_through_audit_transaction(monkeypatch):
    async def check():
        writes = []
        db = SimpleNamespace(
            add=lambda account: None,
            flush=AsyncMock(
                side_effect=IntegrityError(None, None, Exception("duplicate"))
            ),
        )

        @asynccontextmanager
        async def audit_transaction(*args):
            yield db
            writes.append(args)

        monkeypatch.setattr(admin, "admin_write", audit_transaction)
        monkeypatch.setattr(admin.to_thread, "run_sync", AsyncMock(return_value="hash"))
        service = admin.AdminService(SimpleNamespace())
        with pytest.raises(AppError) as conflict:
            await service.create_console_account(
                "duplicate",
                "password",
                "admin",
                cookie="cookie",
                csrf="csrf",
                request_id=None,
                reason="Hiring",
            )
        assert conflict.value.code == "admin_username_taken"
        assert writes == []

    asyncio.run(check())


def test_capped_turn_uses_recorded_opening_time(monkeypatch):
    async def check():
        game = OnlineGame.seeded(2, 123)
        assert game.turn is not None
        seats = [
            GameSeat(player_id=uuid4(), display_name=str(index), ready=True, bot=False)
            for index in range(2)
        ]
        state = MatchState(
            id=uuid4(),
            room_id=uuid4(),
            mode="ranked",
            seats=seats,
            native=game.snapshot(),
            started_ms=0,
            limit_ms=60_000,
            deadline_ms=60_000,
            turn_opened_ms=50_000,
            turn=game.turn,
        )
        service = MatchService(
            SimpleNamespace(
                redis=SimpleNamespace(register_script=lambda _: None),
                settings=Settings(_env_file=None, turn_seconds=40),
            )
        )
        repo = SimpleNamespace(
            get=AsyncMock(return_value=state),
            execute=AsyncMock(),
            cached_ack=AsyncMock(return_value=None),
            now_ms=AsyncMock(return_value=50_125),
        )
        monkeypatch.setattr(service, "repo", repo)
        commit = AsyncMock()
        monkeypatch.setattr(service, "commit_play", commit)
        card = json.loads(game.view(game.turn))["legal_moves"][0]
        await service.play(
            state.id,
            seats[game.turn].player_id,
            "socket",
            PlayRequest(card=card, expected_version=0, request_id=uuid4()),
        )
        events = commit.await_args.args[2]
        assert events[0]["think_ms"] == 125

    asyncio.run(check())
