from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MediaView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pack_key: str
    character_id: str
    slot: str
    bytes: int
    created_at: datetime
    published_at: datetime | None
    withdrawn_at: datetime | None


class MediaReview(BaseModel):
    decision: Literal["publish", "withdraw"]
    reason: str = Field(min_length=3, max_length=120)
