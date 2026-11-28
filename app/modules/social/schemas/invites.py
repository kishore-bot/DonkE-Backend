from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Path
from pydantic import BaseModel

InviteCode = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{8}$")]


class InviteLink(BaseModel):
    code: str
    url: str
    expires_in: int


# Room invites and links -----------------------------------------------------


class RoomInvite(BaseModel):
    room_id: UUID
    from_id: UUID
    from_name: str
    expires_at: datetime
