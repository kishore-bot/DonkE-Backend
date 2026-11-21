import asyncio
import logging
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast

from app.core.platform import Platform
from app.modules.ai.provider import AIProvider, Gemini, Selected, Written

logger = logging.getLogger(__name__)

RESERVE = """
if tonumber(redis.call('GET', KEYS[2]) or '0') >= 3 then return 0 end
if tonumber(redis.call('HGET', KEYS[1], ARGV[1]) or '0') >= tonumber(ARGV[2]) then return 0 end
redis.call('HINCRBY', KEYS[1], ARGV[1], 1)
redis.call('HINCRBY', KEYS[1], ARGV[3], 1)
redis.call('EXPIRE', KEYS[1], 172800)
return 1
"""
FAILURE = """
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], 60)
"""


class Gateway:
    def __init__(self, platform: Platform, provider: AIProvider | None):
        self.platform = platform
        self.provider = provider
        self.limit = asyncio.Semaphore(4)

    def key(self, name: str) -> str:
        return f"{self.platform.settings.redis_prefix}:ai:{name}"

    def usage_key(self) -> str:
        return self.key(f"usage:{datetime.now(UTC).date()}")

    async def usage(self) -> dict[str, int]:
        raw = await self.platform.redis.hgetall(self.usage_key())
        return {name: int(total) for name, total in cast(dict[str, str], raw).items()}

    async def call[T](
        self,
        feature: str,
        operation: Callable[[AIProvider], Awaitable[T]],
        *,
        voice: bool = False,
    ) -> T | None:
        provider = self.provider
        if provider is None:
            return None
        config = self.platform.settings
        budget = config.ai_voice_daily_calls if voice else config.ai_text_daily_calls
        bucket = "voice" if voice else "text"
        usage = self.usage_key()
        breaker = self.key(f"breaker:{bucket}")
        redis = self.platform.redis
        allowed = await redis.execute_command(
            "EVAL",
            RESERVE,
            2,
            usage,
            breaker,
            f"{bucket}_calls",
            budget,
            f"{feature}_calls",
        )
        if not allowed:
            return None
        try:
            async with asyncio.timeout(12 if voice else 6), self.limit:
                result = await operation(provider)
        except Exception as error:  # noqa: BLE001 - AI provider failures fall back.
            logger.info("AI %s request failed (%s)", feature, type(error).__name__)
            await redis.hincrby(usage, f"{feature}_failures", 1)
            await redis.execute_command("EVAL", FAILURE, 1, breaker)
            return None
        await redis.delete(breaker)
        if isinstance(result, Selected | Written):
            await redis.hincrby(usage, f"{feature}_tokens", max(0, result.tokens))
        return result

    async def select(self, task: str, prompt: str, allowed: set[str]) -> str | None:
        result = await self.call(task, lambda provider: provider.select(task, prompt))
        if result is None:
            return None
        if result.key in allowed:
            return result.key
        await self.platform.redis.hincrby(self.usage_key(), f"{task}_invalid", 1)
        return None

    async def embeddings(
        self, texts: list[str], *, query: bool
    ) -> list[list[float]] | None:
        response = await self.call(
            "embedding_query" if query else "embedding_index",
            lambda provider: provider.embed(texts, query=query),
        )
        if (
            response is None
            or len(response) != len(texts)
            or any(
                len(values) != 768 or not all(math.isfinite(value) for value in values)
                for values in response
            )
        ):
            return None
        return response


@asynccontextmanager
async def open_gateway(
    platform: Platform, provider: AIProvider | None = None
) -> AsyncIterator[Gateway]:
    client = (
        Gemini(platform.settings)
        if provider is None and platform.settings.gemini_api_key
        else None
    )
    try:
        yield Gateway(platform, provider or client)
    finally:
        if client is not None:
            await client.close()
