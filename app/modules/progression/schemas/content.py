from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.game.schemas.story import StoryRoute


class CharacterPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    title: str
    stage_theme: Literal["crimson", "tempest"]
    model_url: str


class SeasonPack(BaseModel):
    model_config = ConfigDict(frozen=True)

    anime_id: str
    title: str
    description: str
    cast: tuple[CharacterPreview, ...]
    routes: tuple[StoryRoute, ...] = ()


class SeasonManifest(BaseModel):
    season_id: UUID
    pack_key: str
    starts_at: datetime
    ends_at: datetime
    pack: SeasonPack


class SelectCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1, max_length=40)


class CharacterSelection(BaseModel):
    character_id: str | None
