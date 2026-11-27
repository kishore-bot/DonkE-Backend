import asyncio
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx2 import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.modules.admin import flags
from app.modules.ai import fair_play
from app.modules.matches import repository, service
from app.modules.matches.health import heartbeat_key, online_health, record_turn_sweep
from app.workers import matchmaking


def test_worker_polls_independently_and_refills_turn_capacity(monkeypatch):
    async def check():
        stop, release = asyncio.Event(), asyncio.Event()
        matching, settling, starting = asyncio.Event(), asyncio.Event(), asyncio.Event()
        slow_started, later_started = asyncio.Event(), asyncio.Event()
        games = [uuid4() for _ in range(5)]
        pending = games.copy()
        platform = MagicMock()
        platform.settings = Settings(_env_file=None, matchmaking_poll_seconds=0.001)
        platform.redis.set = AsyncMock()
        matches = MagicMock(platform=platform)
        matches.repo.due = AsyncMock(side_effect=lambda _: pending.copy())
        matches.repo.now_ms = AsyncMock(return_value=1)

        async def match(_lobby):
            matching.set()
            await release.wait()

        async def settle():
            settling.set()
            await release.wait()

        async def start():
            starting.set()

        async def turn(game_id):
            if game_id == games[0]:
                slow_started.set()
                await release.wait()
            if game_id == games[-1]:
                later_started.set()
            pending.remove(game_id)

        matches.start_ready_rooms = start
        matches.settle_finished = settle
        matches.on_deadline = turn
        monkeypatch.setattr(matchmaking, "MatchService", lambda _: matches)
        monkeypatch.setattr(matchmaking, "match_once", match)
        worker = asyncio.create_task(matchmaking.run(platform, stop))
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(
                        event.wait()
                        for event in (
                            matching,
                            settling,
                            starting,
                            slow_started,
                            later_started,
                        )
                    )
                ),
                timeout=2,
            )
            assert pending == [games[0]]
            platform.redis.set.assert_awaited()
        finally:
            stop.set()
            release.set()
            await asyncio.wait_for(worker, timeout=2)

    asyncio.run(check())


@asynccontextmanager
async def redis_platform():
    dsn = os.getenv("TEST_REDIS_DSN")
    if not dsn:
        pytest.skip("Set TEST_REDIS_DSN to a disposable Redis server")
    prefix = f"test-{uuid4().hex}"
    async with Redis.from_url(dsn, decode_responses=True) as redis:
        platform = MagicMock(
            redis=redis,
            settings=Settings(_env_file=None, redis_prefix=prefix),
            ready=AsyncMock(),
        )
        try:
            yield platform
        finally:
            keys = [key async for key in redis.scan_iter(match=f"{prefix}:*")]
            if keys:
                await redis.delete(*keys)


@pytest.mark.integration
def test_turn_renewal_outlasts_initial_lease_and_release_checks_owner(monkeypatch):
    monkeypatch.setattr(repository, "TURN_LEASE_MS", 400)
    monkeypatch.setattr(service, "TURN_LEASE_MS", 400)

    async def check():
        async with redis_platform() as platform:
            matches = service.MatchService(platform)
            game = uuid4()
            observed = []

            async def slow_turn(game_id, owner):
                await asyncio.sleep(0.65)
                acquired = await matches.repo.acquire_turn(game_id, "other")
                renewed = await matches.repo.renew_turn(game_id, "other")
                await matches.repo.release_turn(game_id, "other")
                current_owner = await platform.redis.get(
                    matches.repo.game_key("lease", game)
                )
                observed.append((acquired, renewed, current_owner == owner))

            monkeypatch.setattr(matches, "play_due_turn", slow_turn)
            await matches.on_deadline(game)
            assert observed == [(False, False, True)]
            assert await matches.repo.acquire_turn(game, "next")

    asyncio.run(check())


@pytest.mark.integration
def test_online_health_requires_fresh_heartbeat_and_reports_turn_lag():
    async def check():
        async with redis_platform() as platform:
            with pytest.raises(AppError) as missing:
                await online_health(platform)
            assert missing.value.code == "game_worker_unavailable"
            repo = repository.MatchRepository(platform)
            now = await repo.now_ms()
            await platform.redis.zadd(
                repo.game_key("index", "turns"), {str(uuid4()): now - 200}
            )
            await record_turn_sweep(platform, now)
            health = await online_health(platform)
            assert health.oldest_due_turn_lag_ms == 200 + health.heartbeat_age_ms
            assert await platform.redis.ttl(heartbeat_key(platform)) > 0
            app = create_app(platform.settings)
            app.state.platform = platform
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                healthy = await client.get("/api/v1/online/health")
                assert healthy.status_code == 200
                assert healthy.headers["cache-control"] == "no-store"
                assert healthy.json()["oldest_due_turn_lag_ms"] >= 200
                await record_turn_sweep(platform, now - 11_000)
                unavailable = await client.get("/api/v1/online/health")
                assert unavailable.status_code == 503
                assert unavailable.json()["error"]["code"] == "game_worker_unavailable"
                assert (await client.get("/ready")).status_code == 200

    asyncio.run(check())


@pytest.mark.integration
def test_fair_play_claim_skips_old_leases_and_recovers_expired_claim():
    async def check():
        async with redis_platform() as platform:
            key = fair_play.pending_key(platform)
            await platform.redis.zadd(key, {"old": 1, "first": 2, "second": 3})
            await platform.redis.set(f"{key}:lease:old", "1", ex=300)
            left, right = await asyncio.gather(
                fair_play.claim_pending(platform, 1),
                fair_play.claim_pending(platform, 1),
            )
            assert sorted(left + right) == ["first", "second"]
            assert await fair_play.claim_pending(platform, 1) == []
            await platform.redis.delete(f"{key}:lease:first")
            await platform.redis.zadd(key, {"first": 1})
            assert await fair_play.claim_pending(platform, 1) == ["first"]

    asyncio.run(check())


@pytest.mark.integration
def test_slow_flag_cache_fill_cannot_publish_after_invalidation(monkeypatch):
    async def check():
        async with redis_platform() as platform:
            stale_read, allow_publish = asyncio.Event(), asyncio.Event()
            first_read = True

            async def read(_db):
                nonlocal first_read
                if first_read:
                    first_read = False
                    stale_read.set()
                    await allow_publish.wait()
                    return {"ai_enabled": True}
                return {"ai_enabled": False}

            platform.sessions.return_value.__aenter__ = AsyncMock()
            platform.sessions.return_value.__aexit__ = AsyncMock()
            monkeypatch.setattr(flags, "overrides_in", read)
            refresh = asyncio.create_task(flags.current(platform))
            try:
                await asyncio.wait_for(stale_read.wait(), timeout=2)
                await flags.invalidate(platform)
                assert (await flags.current(platform))["ai_enabled"] is False
            finally:
                allow_publish.set()
                stale_call = await asyncio.wait_for(refresh, timeout=2)
            assert stale_call["ai_enabled"] is False
            assert (
                await platform.redis.hget(flags.cache_key(platform), "ai_enabled")
                == "false"
            )

    asyncio.run(check())
