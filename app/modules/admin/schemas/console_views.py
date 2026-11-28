from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.admin.schemas.auth import Role


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
