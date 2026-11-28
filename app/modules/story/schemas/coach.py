from pydantic import BaseModel, Field

from app.modules.game.schemas.cards import Card
from app.modules.game.schemas.story import StoryEvent


class RivalEvidence(BaseModel):
    intent: str
    source: str
    card: Card
    candidate_count: int
    played_safe_rate: float
    best_safe_rate: float


class DuelCoach(BaseModel):
    evidence: RivalEvidence | None = None
    answer: str
    citation: str | None = None
    replay_event: StoryEvent | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
