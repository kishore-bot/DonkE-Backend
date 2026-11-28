from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.game.schemas.story import StoryObjective
from app.modules.story.helpers.awakening import AWAKENING_POINTS, PATH_VERSION
from app.modules.story.schemas.awakening import PathStep, Requirement


class StoryProgress(BaseModel):
    cleared: bool
    points: int
    target: int = AWAKENING_POINTS
    awakened_character_id: str | None
    missing: list[Requirement]


class StoryResult(BaseModel):
    escaped: bool
    first_clear: bool
    coins: int
    points: int
    objective: StoryObjective | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class AwakeningPath(StoryProgress):
    version: str = PATH_VERSION
    character_id: str | None
    claim_deadline: datetime
    claim_available: bool
    steps: list[PathStep]


class PendingAwakening(BaseModel):
    season_id: UUID
    title: str
