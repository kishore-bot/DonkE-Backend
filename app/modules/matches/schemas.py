from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.game.schemas import PlayerView
from app.modules.lobby.schemas import Mode, Seat


class GameSeat(Seat):
    consecutive_timeouts: int = 0
    timeouts: int = 0
    forfeited: bool = False


class MatchState(BaseModel):
    id: UUID
    room_id: UUID
    mode: Mode | None
    seats: list[GameSeat]
    native: str
    version: int = 0
    sequence: int = 1
    status: Literal["active", "finished"] = "active"
    started_ms: int
    limit_ms: int
    deadline_ms: int
    turn: int | None
    outcome: dict[str, Any] | None = None


class PublicMatch(BaseModel):
    id: UUID
    status: Literal["active", "finished"]
    sequence: int
    version: int
    turn_deadline_ms: int | None
    outcome: dict[str, Any] | None
    seats: list[GameSeat]
    view: PlayerView


class EventBatch(BaseModel):
    sequence: int
    events: list[dict[str, Any]]


class Acknowledgement(BaseModel):
    version: int
    sequence: int


class MatchReplay(BaseModel):
    id: UUID
    room_id: UUID
    mode: Mode | None
    seats: list[GameSeat]
    outcome: dict[str, Any]
    events: list[EventBatch]
