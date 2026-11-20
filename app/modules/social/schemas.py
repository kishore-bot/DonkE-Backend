from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.identity.schemas import Profile


class FriendStatus(BaseModel):
    player: Profile
    status: Literal["incoming", "outgoing", "friends"]


class PartyView(BaseModel):
    id: UUID
    leader_id: UUID
    members: list[Profile]
