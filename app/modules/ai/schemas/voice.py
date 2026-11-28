from typing import Literal

from pydantic import BaseModel

from app.modules.identity.schemas.profile import Language, VoiceId


class VoiceStatus(BaseModel):
    status: Literal["disabled", "pending", "ready", "failed"]


class VoiceOption(BaseModel):
    id: VoiceId
    label: str
    style: str
    default_for: list[Language]
    selected: bool
