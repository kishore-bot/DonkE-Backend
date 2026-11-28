from pydantic import BaseModel, ConfigDict, Field

from app.modules.game.schemas.emotes import SceneEmote


class EmoteSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str | None = Field(min_length=1, max_length=80)


class SeasonEmotes(BaseModel):
    selected: SceneEmote
    options: list[SceneEmote]
