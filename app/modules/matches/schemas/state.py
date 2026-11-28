from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.game.schemas.views import PlayerView
from app.modules.lobby.schemas.queue import Mode
from app.modules.lobby.schemas.rooms import Seat


class GameSeat(Seat):
    consecutive_timeouts: int = 0
    timeouts: int = 0
    forfeited: bool = False
    left: bool = False
    # Bot seats only: engine level, search depth, persona and rival owner.
    level: Literal["easy", "medium", "hard"] | None = None
    iterations: int = 200
    persona: Literal["thug", "professor", "aunty"] | None = None
    rival_of: UUID | None = None


class MatchAdmission(BaseModel):
    season_id: UUID | None
    season_title: str | None = None
    pack_key: str | None = None
    rules_version: str = "kazhutha-v1"


class MatchState(BaseModel):
    id: UUID
    room_id: UUID
    mode: Mode | None
    seats: list[GameSeat]
    native: str
    # The opening deal, kept so a finished match can be re-played for coaching.
    opening: str | None = None
    admission: MatchAdmission | None = None
    version: int = 0
    sequence: int = 1
    status: Literal["active", "finished"] = "active"
    started_ms: int
    limit_ms: int
    deadline_ms: int
    turn_opened_ms: int | None = None
    prepare_until_ms: int | None = None
    turn: int | None
    outcome: dict[str, Any] | None = None


class PublicMatch(BaseModel):
    id: UUID
    status: Literal["active", "finished"]
    sequence: int
    version: int
    turn_deadline_ms: int | None
    prepare_until_ms: int | None = None
    server_now_ms: int | None = None
    outcome: dict[str, Any] | None
    seats: list[GameSeat]
    view: PlayerView
    admission: MatchAdmission | None = None


class EventBatch(BaseModel):
    sequence: int
    events: list[dict[str, Any]]


class Acknowledgement(BaseModel):
    version: int
    sequence: int
