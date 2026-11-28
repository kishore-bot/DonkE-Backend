from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.lobby.schemas.queue import Mode


class Seat(BaseModel):
    player_id: UUID | None = None
    display_name: str
    ready: bool
    bot: bool


class Room(BaseModel):
    id: UUID
    host_id: UUID
    capacity: int
    status: Literal["waiting", "ready", "playing", "finished"]
    revision: int = 0
    start_at_ms: int | None = None
    game_id: UUID | None = None
    mode: Mode | None = None
    seats: list[Seat]


class RoomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity: int = Field(default=4, ge=2, le=5, strict=True)


class ReadyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool = Field(strict=True)
