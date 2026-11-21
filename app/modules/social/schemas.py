from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.schemas import Profile

Activity = Literal["idle", "queued", "matching", "matched", "room"]


class FriendStatus(BaseModel):
    player: Profile
    status: Literal["incoming", "outgoing", "friends"]
    # Accepted friends only: live presence and what they are doing.
    online: bool = False
    activity: Activity | None = None


class Together(BaseModel):
    """Head-to-head record across matches both players finished."""

    games: int
    ahead: int
    behind: int
    tied: int
    my_donkeys: int
    their_donkeys: int


class InviteLink(BaseModel):
    code: str
    url: str
    app_link: str
    expires_in: int


class ChatPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=400)


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


class PartyView(BaseModel):
    id: UUID
    leader_id: UUID
    members: list[Profile]
