from typing import Literal

from pydantic import BaseModel

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.matches.repository import MatchRepository

HEARTBEAT_SECONDS = 10


class OnlineHealth(BaseModel):
    status: Literal["ok"] = "ok"
    heartbeat_age_ms: int
    oldest_due_turn_lag_ms: int


def heartbeat_key(platform: Platform) -> str:
    return f"{platform.settings.redis_prefix}:game:worker:heartbeat"


async def record_turn_sweep(platform: Platform, redis_time_ms: int) -> None:
    await platform.redis.set(
        heartbeat_key(platform), redis_time_ms, ex=HEARTBEAT_SECONDS
    )


async def online_health(platform: Platform) -> OnlineHealth:
    await platform.ready()
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
