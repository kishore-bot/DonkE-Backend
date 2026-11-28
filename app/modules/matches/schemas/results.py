from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.lobby.schemas.queue import Mode
from app.modules.matches.schemas.state import EventBatch, GameSeat, MatchAdmission


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
