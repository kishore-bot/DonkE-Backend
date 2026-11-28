from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.modules.game.schemas.cards import Suit
from app.modules.game.schemas.emotes import SceneEmote
from app.modules.game.schemas.story import StoryEvent, StoryRoute

type RivalIntent = Literal["steady", "pressure"]


@dataclass(frozen=True, slots=True)
class StoryPin:
    season_id: UUID
    pack_key: str
    character_id: str
    player_id: UUID | None
    intent: RivalIntent = "steady"
    intent_source: Literal["gemini", "engine"] = "engine"
    squad_party_id: UUID | None = None
    chapter_id: str = "trial"
    emote: SceneEmote = field(default_factory=SceneEmote)
    route: StoryRoute | None = None
    rival_budget: int | None = None
    target_rating: int | None = None
    remembered: StoryEvent | None = None
    rival_avoid_suit: Suit | None = None
    rival_expert: bool = False
