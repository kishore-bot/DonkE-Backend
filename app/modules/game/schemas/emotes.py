from typing import Literal

from pydantic import BaseModel, ConfigDict

type EmoteMotion = Literal["resolve", "salute", "flourish"]


class SceneEmote(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str | None = None
    title: str = "Standard celebration"
    motion: EmoteMotion = "resolve"
