from typing import Literal

from pydantic import BaseModel

from app.modules.identity.schemas.profile import Profile

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
