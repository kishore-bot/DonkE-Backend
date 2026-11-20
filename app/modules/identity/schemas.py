from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["ml", "ta", "hi", "kn", "te", "en"]


class GoogleSignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_token: str = Field(min_length=1, max_length=8192, repr=False)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=160, repr=False)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language


class Profile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    language: Language
    mmr: int


class SessionTokens(BaseModel):
    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
