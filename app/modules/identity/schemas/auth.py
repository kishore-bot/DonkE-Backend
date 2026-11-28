from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GoogleSignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_token: str = Field(min_length=1, max_length=8192, repr=False)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=160, repr=False)


class SessionTokens(BaseModel):
    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - a token type, not a secret
    expires_in: int
