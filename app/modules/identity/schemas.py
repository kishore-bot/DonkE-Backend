from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Language = Literal["ml", "ta", "hi", "kn", "te", "en"]
# Curated Gemini TTS voices; each speaks every supported language.
VoiceId = Literal["kore", "puck", "leda", "aoede"]
VOICES: dict[VoiceId, tuple[str, str]] = {
    "kore": ("Calm commentator", "Steady and clear, like a radio caster"),
    "puck": ("Energetic caster", "Fast and excited on every Vettu"),
    "leda": ("Warm storyteller", "Friendly, like an uncle at the table"),
    "aoede": ("Playful friend", "Bright and teasing, full of banter"),
}
DEFAULT_VOICE: dict[Language, VoiceId] = {
    "ml": "kore",
    "ta": "leda",
    "hi": "puck",
    "kn": "aoede",
    "te": "leda",
    "en": "puck",
}


class GoogleSignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_token: str = Field(min_length=1, max_length=8192, repr=False)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=160, repr=False)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language | None = None
    voice: VoiceId | None = None

    @model_validator(mode="after")
    def needs_a_field(self) -> ProfileUpdate:
        if self.language is None and self.voice is None:
            raise ValueError("Send a language or a voice")
        return self


class Profile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    language: Language
    mmr: int
    voice: VoiceId | None = None

    @property
    def commentary_voice(self) -> VoiceId:
        """The player's chosen voice, or the default for their language."""
        return self.voice or DEFAULT_VOICE[self.language]


class SessionTokens(BaseModel):
    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
