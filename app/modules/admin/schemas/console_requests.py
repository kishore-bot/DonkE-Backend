from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.admin.schemas.auth import USERNAME, Role


class Reason(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=3, max_length=120)


class CoinGrant(Reason):
    amount: int = Field(ge=-10_000, le=10_000)


class CosmeticGrant(Reason):
    sku: str = Field(min_length=1, max_length=80)


class MuteRequest(Reason):
    minutes: int = Field(ge=0, le=60 * 24 * 30)  # 0 lifts the mute


class ReportResolve(Reason):
    decision: Literal["dismissed", "actioned"]


class FlagUpdate(Reason):
    value: bool | int | str | None


class AdminCreate(Reason):
    username: str = Field(pattern=USERNAME)
    password: str = Field(min_length=12, max_length=256, repr=False)
    role: Role


class AdminUpdate(Reason):
    role: Role | None = None
    active: bool | None = None
