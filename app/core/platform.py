from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings
from app.core.errors import AppError

SCHEMA_HEAD = "20261127_season_cues"


class Base(DeclarativeBase):
    pass


@dataclass(frozen=True, slots=True)
class Platform:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis

    async def ready(self) -> None:
        async with self.engine.connect() as connection:
            versions = set(
                await connection.scalars(
                    text("SELECT version_num FROM alembic_version")
                )
            )
            if not versions:
                raise AppError(
                    503, "schema_unavailable", "Online storage has not been initialized"
                )
            if versions != {SCHEMA_HEAD}:
                # Imported here: app.core.schema imports every module's models.
                from app.core.schema import has_required_schema  # noqa: PLC0415

                if not await connection.run_sync(has_required_schema):
                    raise AppError(
                        503,
                        "schema_mismatch",
                        "Online storage needs the application migration",
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
