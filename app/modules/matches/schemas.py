from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

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
    admission: MatchAdmission | None = None


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
    admission: MatchAdmission | None = None


class PublicReplay(BaseModel):
    """A finished match as players may see it: public events only."""

    id: UUID
    room_id: UUID
    mode: Mode | None
    seats: list[GameSeat]
    outcome: dict[str, Any]
    events: list[EventBatch]
    admission: MatchAdmission | None = None

    @classmethod
    def of(cls, replay: MatchReplay) -> PublicReplay:
        return cls.model_validate(replay.model_dump(exclude={"opening"}))


class MatchRewards(BaseModel):
    coins: int = 0
    season_points: int = 0
    bank_coins: int = 0
    mmr_delta: int = 0


class UnsettledResult(BaseModel):
    status: Literal["in_progress", "pending"]
    admission: MatchAdmission | None = None


class SettledResult(BaseModel):
    status: Literal["settled"] = "settled"
    admission: MatchAdmission | None = None
    rewarded_season_id: UUID | None = None
    finished_at: datetime
    outcome: str
    placement: Literal["escaped", "donkey", "forfeited", "holding"]
    place: int | None = None
    rewards: MatchRewards | None = None


type MatchResult = Annotated[
    UnsettledResult | SettledResult, Field(discriminator="status")
]


class RecentMatch(BaseModel):
    game_id: UUID
    finished_at: datetime
