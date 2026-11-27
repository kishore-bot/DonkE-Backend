from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.game.schemas import PracticeCreated, SceneEmote, StoryEvent, StoryRoute
from app.modules.progression.season_content import CharacterPreview
from app.modules.story.chapters import (
    OPENING_CHAPTER,
)


class StartDuel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    season_id: UUID
    chapter_id: str = Field(default=OPENING_CHAPTER, min_length=1, max_length=40)
    adaptive: bool = False
    character_id: str | None = Field(default=None, min_length=1, max_length=40)
    route: StoryRoute | None = None


class StoryAttempt(PracticeCreated):
    season_id: UUID
    pack_key: str
    chapter_id: str
    chapter_title: str
    rival: str
    character: CharacterPreview
    rewards_eligible: bool
    emote: SceneEmote
    rival_memory: StoryEvent | None = None
    rival_target_rating: int | None = None
    rival_intent: str = "steady"


class ResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_token: str = Field(min_length=1, max_length=128, repr=False)
