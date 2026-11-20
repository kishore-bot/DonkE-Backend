from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["classic", "ranked"]


class Seat(BaseModel):
    player_id: UUID | None = None
    display_name: str
    ready: bool
    bot: bool


class Room(BaseModel):
    id: UUID
    host_id: UUID
    capacity: int
    status: Literal["waiting", "ready"]
    mode: Mode | None = None
    seats: list[Seat]


class RoomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity: int = Field(default=4, ge=2, le=5, strict=True)


class ReadyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool = Field(strict=True)


class QueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode = "classic"


class QueueStatus(BaseModel):
    status: Literal["idle", "queued", "matching", "matched", "room"]
    mode: Mode | None = None
    room_id: UUID | None = None
    enqueued_at_ms: int | None = None
