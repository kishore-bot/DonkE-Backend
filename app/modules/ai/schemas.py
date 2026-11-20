from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.schemas import Language


class Commentary(BaseModel):
    language: Language
    text: str
    source: Literal["script", "gemini"]


class VoiceStatus(BaseModel):
    status: Literal["disabled", "pending", "ready", "failed"]


class CoachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=400)


class CoachReply(BaseModel):
    answer: str
    citation: str | None = None
    source: Literal["rules", "gemini_selected", "no_match"]


class ReindexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=3, max_length=120)
