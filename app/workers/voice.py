import asyncio
import logging

from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.platform import open_platform
from app.modules.ai.services.gateway import open_gateway
from app.modules.ai.services.voice import Voice

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = Settings()
    async with open_platform(settings) as platform, open_gateway(platform) as gateway:
        if gateway.provider is None:
            return  # No AI backend configured: nothing to voice.
        voice = Voice(gateway)
        while True:
            try:
                if await voice.tick():
                    continue
            except RedisError as exc:
                logger.warning("Voice tick failed (%s)", type(exc).__name__)
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
