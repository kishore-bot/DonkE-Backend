from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CaseView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    player_id: UUID
    status: str
    score: int
    stats: dict[str, Any]
    note: str | None
    created_at: datetime
    resolved_at: datetime | None


class Resolve(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["dismissed", "confirmed"]
    reason: str = Field(min_length=3, max_length=200)
