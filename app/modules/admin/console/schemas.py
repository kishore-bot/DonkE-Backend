from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.admin.schemas import USERNAME, Role
from app.modules.matches.models import MatchRecord


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


class Dashboard(BaseModel):
    players: int
    new_players_24h: int
    matches_24h: int
    active_games: int
    open_fair_play_cases: int
    ai_usage: dict[str, int]
    flags: dict[str, Any]


class PlayerRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    language: str
    mmr: int
    active: bool
    created_at: datetime


class MatchRow(BaseModel):
    id: UUID
    finished_at: datetime
    mode: str | None
    outcome: dict[str, Any]
    players: list[str]


class PlayerDetail(BaseModel):
    player: PlayerRow
    coins: int
    stats: dict[str, int]
    skill: dict[str, float] | None
    cosmetics: list[str]
    recent_matches: list[MatchRow]
    open_cases: int
    open_reports: int
    muted_until: datetime | None


class StoreItem(BaseModel):
    sku: str
    label: str
    slot: str
    price: int
    festival: str | None
    available: bool
    owners: int


class FlagView(BaseModel):
    key: str
    value: Any
    description: str


class AdminRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: Role
    active: bool
    totp_enabled: bool
    last_login_at: datetime | None


def match_row(record: MatchRecord) -> MatchRow:
    replay = record.replay
    return MatchRow(
        id=record.id,
        finished_at=record.finished_at,
        mode=replay.get("mode"),
        outcome=replay.get("outcome", {}),
        players=[seat.get("display_name", "?") for seat in replay.get("seats", [])],
    )
