from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    player_id: UUID
    reason: Literal["abuse", "cheating", "afk", "name", "other"]
    game_id: UUID | None = None
    note: str | None = Field(default=None, max_length=300)


class ReportView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reporter_id: UUID
    target_id: UUID
    reason: str
    game_id: UUID | None
    note: str | None
    status: str
    resolution: str | None
    created_at: datetime
