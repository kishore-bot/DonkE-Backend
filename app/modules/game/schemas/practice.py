from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.game.schemas.cards import Card
from app.modules.game.schemas.views import GameUpdate


class PracticeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seats: int = Field(default=4, ge=2, le=5, strict=True)
    level: Literal["easy", "medium", "hard"] = "medium"


class MoveScore(BaseModel):
    card: Card
    safe_rate: float


class PracticeHint(BaseModel):
    """Engine scores for the human's legal moves, best first."""

    best: Card | None
    options: list[MoveScore]


class PracticeCreated(GameUpdate):
    game_id: UUID
    access_token: str


class PlayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_version: int = Field(ge=0, strict=True)
    card: Card


class PracticePlayRequest(PlayRequest):
    call_strike: bool = Field(default=False, strict=True)
