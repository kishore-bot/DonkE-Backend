from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class Platform:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis


@asynccontextmanager
async def open_platform(settings: Settings) -> AsyncIterator[Platform]:
    if settings.postgres_dsn is None or settings.redis_dsn is None:
        raise ValueError("Online platform settings are required")
    engine = create_async_engine(
        str(settings.postgres_dsn),
        pool_pre_ping=True,
        pool_timeout=3,
        connect_args={"timeout": 3, "command_timeout": 5},
    )
    redis = Redis.from_url(
        str(settings.redis_dsn),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        yield Platform(
            settings, engine, async_sessionmaker(engine, expire_on_commit=False), redis
        )
    finally:
        try:
            await redis.aclose()
        finally:
            await engine.dispose()
