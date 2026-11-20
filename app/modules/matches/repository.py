import json
from pathlib import Path
from typing import cast
from uuid import UUID

from app.core.platform import Platform
from app.modules.lobby.schemas import Room
from app.modules.matches.schemas import EventBatch, MatchState

SCRIPT = Path(__file__).with_name("game.lua").read_text(encoding="utf-8")


class MatchConflict(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MatchRepository:
    def __init__(self, platform: Platform):
        self.redis = platform.redis
        self.prefix = platform.settings.redis_prefix
        self.script = self.redis.register_script(SCRIPT)

    def game_key(self, kind: str, identifier: str | UUID) -> str:
        return f"{self.prefix}:game:{kind}:{identifier}"

    async def now_ms(self) -> int:
        seconds, micros = await self.redis.time()
        return seconds * 1000 + micros // 1000

    async def execute(
        self, operation: str, game_id: UUID, **args: str | int | bool
    ) -> dict:
        value = await self.script(
            keys=[self.prefix],
            args=[operation, json.dumps({"game_id": str(game_id), **args})],
        )
        result = json.loads(value)
        if "error" in result:
            raise MatchConflict(result["error"])
        return result

    async def room(self, room_id: UUID) -> Room | None:
        raw = await self.redis.get(f"{self.prefix}:lobby:room:{room_id}")
        return Room.model_validate_json(raw) if raw else None

    async def get(self, game_id: UUID) -> MatchState | None:
        raw = await self.redis.get(self.game_key("state", game_id))
        return MatchState.model_validate_json(raw) if raw else None

    async def events(self, game_id: UUID, after: int, through: int) -> list[EventBatch]:
        records = await self.redis.xrange(
            self.game_key("events", game_id), f"({after}-0", f"{through}-0"
        )
        return [
            EventBatch(
                sequence=int(identifier.split("-", maxsplit=1)[0]),
                events=json.loads(fields["events"]),
            )
            for identifier, fields in cast(list[tuple[str, dict[str, str]]], records)
        ]

    async def due(self, name: str, *, lobby: bool = False) -> list[UUID]:
        key = (
            f"{self.prefix}:lobby:rooms:ready"
            if lobby
            else self.game_key("index", name)
        )
        raw = await self.redis.zrangebyscore(
            key, "-inf", await self.now_ms(), start=0, num=32
        )
        return [UUID(identifier) for identifier in cast(list[str], raw)]

    async def acquire_turn(self, game_id: UUID, owner: str) -> bool:
        return bool(
            await self.redis.set(
                self.game_key("lease", game_id), owner, nx=True, px=2000
            )
        )

    async def connect(self, game_id: UUID, player_id: UUID, owner: str) -> None:
        await self.redis.set(
            self.game_key("connection", f"{game_id}:{player_id}"), owner, ex=15
        )

    async def cached_ack(self, game_id: UUID, command: str) -> dict | None:
        raw = await self.redis.hget(self.game_key("commands", game_id), command)
        return json.loads(raw) if raw else None
