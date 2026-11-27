from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


# A published key always resolves to the same content. Edits get a new key.
PACKS = {
    "grimoire-awakening-v1": SeasonPack(
        anime_id="grimoire-awakening",
        title="Grimoire Awakening",
        description="Choose a duelist from the grimoire squad.",
        cast=(
            CharacterPreview(
                id="ashblade",
                name="Ashblade",
                title="Crimson duelist",
                stage_theme="crimson",
                model_url="/models/crimson.glb",
            ),
            CharacterPreview(
                id="stormscribe",
                name="Stormscribe",
                title="Tempest duelist",
                stage_theme="tempest",
                model_url="/models/tempest.glb",
            ),
        ),
    ),
    "skybound-voyage-v1": SeasonPack(
        anime_id="skybound-voyage",
        title="Skybound Voyage",
        description="Meet the crew charting a course through the storm.",
        cast=(
            CharacterPreview(
                id="gale",
                name="Gale",
                title="Storm navigator",
                stage_theme="tempest",
                model_url="/models/tempest.glb",
            ),
        ),
    ),
}
