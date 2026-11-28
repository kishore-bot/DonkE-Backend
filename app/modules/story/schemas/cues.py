from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.story.schemas.lines import Moment, VoiceLocale


class CreateCue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pack_key: str = Field(min_length=1, max_length=80)
    character_id: str = Field(min_length=1, max_length=40)
    moment: Moment
    reason: str = Field(min_length=3, max_length=120)


class AdvanceCue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    stage: Literal["english", "japanese", "review"]
    en: str | None = Field(default=None, max_length=180)
    ja: str | None = Field(default=None, max_length=180)
    reason: str = Field(min_length=3, max_length=120)


class CueView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pack_key: str
    character_id: str
    moment: str
    stage: str
    en: str | None
    ja: str | None
    en_source: str | None
    ja_source: str | None


class PublicCue(BaseModel):
    caption: str
    japanese: str
    audio_locale: VoiceLocale | None = None
    audio_url: str | None = Field(default=None, exclude_if=lambda value: value is None)
