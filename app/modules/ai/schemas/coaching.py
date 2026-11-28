from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.ai.schemas.source import Source

Situation = Literal["leading", "following", "cutting", "near_escape"]


class Decision(BaseModel):
    move: int
    situation: Situation
    played: str
    best: str
    played_rate: float
    best_rate: float

    @property
    def gap(self) -> float:
        return self.best_rate - self.played_rate


class Sample(BaseModel):
    """One real decision, kept for fair-play review."""

    think_ms: int | None
    legal: int
    top: bool


class SituationStats(BaseModel):
    decisions: int = 0
    mistakes: int = 0


class Analysis(BaseModel):
    decisions: int
    accuracy: float
    mistakes: list[Decision]
    situations: dict[Situation, SituationStats]
    samples: list[Sample] = []


class Tip(BaseModel):
    move: int
    text: str
    source: Source


class Coaching(BaseModel):
    game_id: UUID
    decisions: int
    accuracy: float
    mistakes: list[Decision]
    situations: dict[Situation, SituationStats]
    tips: list[Tip]
