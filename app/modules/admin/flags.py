"""Runtime flags: a short allowlist of settings operators can change live.

Postgres is the source of truth. Every write mirrors the full set to one Redis
hash, which hot paths read; a missing hash is rebuilt from Postgres. Secrets,
URLs and timers are deliberately not flags.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import DateTime, String, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.errors import AppError
from app.core.platform import Base, Platform


@dataclass(frozen=True, slots=True)
class FlagSpec:
    kind: type
    description: str
    minimum: int = 0
    maximum: int = 0


FLAGS: dict[str, FlagSpec] = {
    "ai_enabled": FlagSpec(bool, "Master switch for every Gemini feature"),
    "commentary_enabled": FlagSpec(bool, "Live commentary lines and voice"),
    "ai_text_daily_calls": FlagSpec(int, "Daily Gemini text call budget", 0, 5000),
    "ai_voice_daily_calls": FlagSpec(int, "Daily Gemini voice call budget", 0, 5000),
    "maintenance_notice": FlagSpec(str, "Banner shown in the app (empty hides it)"),
}


class RuntimeFlag(Base):
    __tablename__ = "runtime_flags"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def defaults(platform: Platform) -> dict[str, Any]:
    settings = platform.settings
    return {
        "ai_enabled": True,
        "commentary_enabled": True,
        "ai_text_daily_calls": settings.ai_text_daily_calls,
        "ai_voice_daily_calls": settings.ai_voice_daily_calls,
        "maintenance_notice": "",
    }


def validate(key: str, value: Any) -> Any:
    spec = FLAGS.get(key)
    if spec is None:
        raise AppError(404, "flag_not_found", "Unknown runtime flag")
    if spec.kind is bool and isinstance(value, bool):
        return value
    if (
        spec.kind is int
        and isinstance(value, int)
        and not isinstance(value, bool)
        and spec.minimum <= value <= spec.maximum
    ):
        return value
    if spec.kind is str and isinstance(value, str) and len(value) <= 200:
        return value.strip()
    raise AppError(
        422, "invalid_flag_value", f"{key} needs a valid {spec.kind.__name__}"
    )


def cache_key(platform: Platform) -> str:
    return f"{platform.settings.redis_prefix}:flags"


LOADED = "__loaded"


async def publish(platform: Platform, db: AsyncSession) -> dict[str, Any]:
    """Mirror only the overrides, so changed settings defaults still apply."""
    overrides = {
        row.key: row.value
        for row in await db.scalars(select(RuntimeFlag))
        if row.key in FLAGS
    }
    key = cache_key(platform)
    mapping = {name: json.dumps(value) for name, value in overrides.items()}
    async with platform.redis.pipeline(transaction=True) as pipe:
        pipe.delete(key)
        pipe.hset(key, mapping={LOADED: "1", **mapping})
        await pipe.execute()
    return {**defaults(platform), **overrides}


async def current(platform: Platform) -> dict[str, Any]:
    """All flags with overrides applied. Hot-path safe: one Redis read."""
    raw = cast("dict[str, str]", await platform.redis.hgetall(cache_key(platform)))
    if LOADED not in raw:
        return await refresh(platform)
    values = defaults(platform)
    values.update(
        {name: json.loads(value) for name, value in raw.items() if name in FLAGS}
    )
    return values


async def refresh(platform: Platform) -> dict[str, Any]:
    """Mirror committed flags to Redis. Call after the write transaction."""
    async with platform.sessions() as db:
        return await publish(platform, db)


async def set_flag(
    platform: Platform, db: AsyncSession, key: str, value: Any | None
) -> None:
    if value is None:
        validate(key, defaults(platform)[key])
        row = await db.get(RuntimeFlag, key)
        if row is not None:
            await db.delete(row)
    else:
        clean = validate(key, value)
        query = insert(RuntimeFlag).values(key=key, value=clean)
        await db.execute(
            query.on_conflict_do_update(
                index_elements=[RuntimeFlag.key],
                set_={"value": query.excluded.value, "updated_at": func.now()},
            )
        )
    await db.flush()
