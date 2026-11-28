from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

Mode = Literal["classic", "ranked"]


class QueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode = "classic"


class QueueStatus(BaseModel):
    status: Literal["idle", "queued", "matching", "matched", "room"]
    mode: Mode | None = None
    room_id: UUID | None = None
    enqueued_at_ms: int | None = None
