"""Runtime flags: a short allowlist of settings operators can change live.

Postgres is the source of truth. Writes invalidate the Redis hash, and reads
rebuild it from committed overrides. Secrets, URLs and timers are not flags.
"""

import json
import logging
from typing import Any, cast

from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.platform import Platform
from app.modules.admin.helpers.flag_specs import FLAGS, defaults, validate
from app.modules.admin.models.runtime_flag import RuntimeFlag

logger = logging.getLogger(__name__)


def cache_key(platform: Platform) -> str:
    return f"{platform.settings.redis_prefix}:flags"


LOADED = "__loaded"


# The Redis copy is a cache, never the source of truth: it expires, so a
# missed invalidation (Redis down mid-write) heals within this many seconds.
CACHE_SECONDS = 30


PUBLISH = """
if (redis.call('GET', KEYS[2]) or '0') ~= ARGV[1] then return 0 end
redis.call('DEL', KEYS[1])
redis.call('HSET', KEYS[1], unpack(ARGV, 3))
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""


def generation_key(platform: Platform) -> str:
    return f"{cache_key(platform)}:generation"


async def overrides_in(db: AsyncSession) -> dict[str, Any]:
    return {
        row.key: row.value
        for row in await db.scalars(select(RuntimeFlag))
        if row.key in FLAGS
    }


async def stored(platform: Platform) -> dict[str, Any]:
    """Flags straight from Postgres, bypassing the cache."""
    async with platform.sessions() as db:
        return {**defaults(platform), **await overrides_in(db)}


async def invalidate(platform: Platform) -> None:
    """Invalidate both the hash and any refresh that started before this write."""
    try:
        async with platform.redis.pipeline(transaction=True) as pipe:
            pipe.incr(generation_key(platform))
            pipe.delete(cache_key(platform))
            await pipe.execute()
    except RedisError:
        logger.warning(
            "Flag cache invalidation failed; it expires in %ss", CACHE_SECONDS
        )


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
    """Publish overrides only if the generation stayed stable across the read."""
    redis = platform.redis
    generation = await redis.get(generation_key(platform)) or "0"
    async with platform.sessions() as db:
        overrides = await overrides_in(db)
    fields = [LOADED, "1"]
    for name, value in overrides.items():
        fields.extend((name, json.dumps(value)))
    published = await redis.execute_command(
        "EVAL",
        PUBLISH,
        2,
        cache_key(platform),
        generation_key(platform),
        generation,
        CACHE_SECONDS,
        *fields,
    )
    if not published:
        # A concurrent write advanced the generation. Read in a fresh session
        # without retrying publication or returning the superseded snapshot.
        return await stored(platform)
    return {**defaults(platform), **overrides}


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
