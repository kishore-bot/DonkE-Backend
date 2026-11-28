from app.core.errors import AppError
from app.core.platform import Platform
from app.core.schema import check_storage_ready
from app.modules.matches.repositories.matches import MatchRepository
from app.modules.matches.schemas.health import OnlineHealth

HEARTBEAT_SECONDS = 10


def heartbeat_key(platform: Platform) -> str:
    return f"{platform.settings.redis_prefix}:game:worker:heartbeat"


async def record_turn_sweep(platform: Platform, redis_time_ms: int) -> None:
    await platform.redis.set(
        heartbeat_key(platform), redis_time_ms, ex=HEARTBEAT_SECONDS
    )


async def online_health(platform: Platform) -> OnlineHealth:
    await check_storage_ready(platform)
    heartbeat = await platform.redis.get(heartbeat_key(platform))
    repo = MatchRepository(platform)
    now = await repo.now_ms()
    age = max(0, now - int(heartbeat)) if heartbeat is not None else None
    if age is None or age >= HEARTBEAT_SECONDS * 1_000:
        raise AppError(503, "game_worker_unavailable", "Game worker is unavailable")
    oldest = await repo.oldest_due_turn_ms(now)
    return OnlineHealth(
        heartbeat_age_ms=age,
        oldest_due_turn_lag_ms=now - oldest if oldest is not None else 0,
    )
