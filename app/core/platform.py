from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings
from app.core.errors import AppError


class Base(DeclarativeBase):
    pass


@dataclass(frozen=True, slots=True)
class Platform:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis

    async def ready(self) -> None:
        # Imported here because the schema loads every model that extends Base.
        from app.core.schema import has_required_schema  # noqa: PLC0415

        async with self.engine.connect() as connection:
            if not await connection.run_sync(has_required_schema):
                raise AppError(
                    503,
                    "schema_mismatch",
                    "Online storage does not have the required tables and pgvector",
                )
        await self.redis.ping()


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


def get_platform(request: Request) -> Platform:
    platform: Platform | None = request.app.state.platform
    if platform is None:
        raise AppError(503, "online_unavailable", "Online play is unavailable")
    return platform
