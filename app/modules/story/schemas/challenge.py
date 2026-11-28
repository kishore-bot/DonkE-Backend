from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.game.dto.story_pin import RivalIntent, StoryPin
from app.modules.game.schemas.cards import Suit
from app.modules.game.schemas.story import StoryRoute
from app.modules.progression.schemas.content import CharacterPreview
from app.modules.story.helpers.chapters import OPENING_CHAPTER


class SharedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    escaped: bool
    plays: int = Field(ge=0, le=1000)


class ChallengeView(BaseModel):
    pack_title: str
    rival: str
    character: CharacterPreview
    result: SharedResult
    expires_at: datetime


class ChallengeLink(BaseModel):
    code: str


class ChallengePin(BaseModel):
    season_id: UUID
    pack_key: str
    character_id: str
    intent: RivalIntent
    chapter_id: str = OPENING_CHAPTER
    result: SharedResult
    exp: datetime
    route: StoryRoute | None = None
    rival_budget: int | None = Field(default=None, ge=0, le=256)
    rival_avoid_suit: Suit | None = None
    rival_expert: bool = False

    def story(self) -> StoryPin:
        return StoryPin(
            self.season_id,
            self.pack_key,
            self.character_id,
            None,
            intent=self.intent,
            chapter_id=self.chapter_id,
            route=self.route,
            rival_budget=self.rival_budget,
            rival_avoid_suit=self.rival_avoid_suit,
            rival_expert=self.rival_expert,
        )
