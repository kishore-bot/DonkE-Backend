from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["viewer", "moderator", "admin"]


USERNAME = r"^[a-z0-9_.-]{3,48}$"


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    username: str = Field(pattern=USERNAME)
    password: str = Field(min_length=1, max_length=256, repr=False)
    totp: str | None = Field(default=None, pattern=r"^\d{6}$", repr=False)


class AdminProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: Role
    totp_enabled: bool = False


class AdminLogin(BaseModel):
    admin: AdminProfile
    csrf_token: str = Field(repr=False)


class TotpSetup(BaseModel):
    secret: str = Field(repr=False)
    uri: str = Field(repr=False)


class TotpCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^\d{6}$", repr=False)
