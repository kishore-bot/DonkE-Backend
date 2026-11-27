from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.game.schemas import PlayerView
from app.modules.lobby.schemas import Mode, Seat


class GameSeat(Seat):
    consecutive_timeouts: int = 0
    timeouts: int = 0
    forfeited: bool = False
    # Bot seats only: engine level, search depth, persona and rival owner.
    level: Literal["easy", "medium", "hard"] | None = None
    iterations: int = 200
    persona: Literal["thug", "professor", "aunty"] | None = None
    rival_of: UUID | None = None


class MatchState(BaseModel):
    id: UUID
    room_id: UUID
    mode: Mode | None
    seats: list[GameSeat]
    native: str
    # The opening deal, kept so a finished match can be re-played for coaching.
    opening: str | None = None
    version: int = 0
    sequence: int = 1
    status: Literal["active", "finished"] = "active"
    started_ms: int
    limit_ms: int
    deadline_ms: int
    turn_opened_ms: int | None = None
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
    # Private: every player's opening hand, kept only for engine analysis.
    # Never return this model to clients; use PublicReplay.
    opening: str | None = None


class PublicReplay(BaseModel):
    """A finished match as players may see it: public events only."""

    id: UUID
    room_id: UUID
    mode: Mode | None
    seats: list[GameSeat]
    outcome: dict[str, Any]
    events: list[EventBatch]

    @classmethod
    def of(cls, replay: MatchReplay) -> PublicReplay:
        return cls.model_validate(replay.model_dump(exclude={"opening"}))
