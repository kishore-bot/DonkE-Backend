import json
from pathlib import Path

from redis.asyncio import Redis

from app.core.config import Settings

SCRIPT = Path(__file__).with_name("lobby.lua").read_text(encoding="utf-8")


class LobbyConflict(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class LobbyRepository:
    def __init__(self, redis: Redis, settings: Settings):
        self.script = redis.register_script(SCRIPT)
        self.prefix = f"{settings.redis_prefix}:lobby"
        self.game_prefix = f"{settings.redis_prefix}:game"
        self.parameters = {
            "room_ttl": settings.room_ttl_seconds,
            "start_delay_ms": round(settings.room_start_seconds * 1000),
            "queue_ttl": settings.queue_ttl_seconds,
            "bot_wait_ms": round(settings.bot_fill_seconds * 1000),
            "lease_ms": max(1, round(settings.claim_lease_seconds * 1000)),
        }

    async def execute(self, operation: str, **fields: str | int | bool) -> dict:
        raw = await self.script(
            keys=[self.prefix, self.game_prefix],
            args=[operation, json.dumps({**self.parameters, **fields})],
        )
        result = json.loads(raw)
        if "error" in result:
            raise LobbyConflict(result["error"])
        return result
