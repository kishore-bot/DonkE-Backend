from uuid import UUID

from fastapi import APIRouter, Request

from app.core.rate_limit import limit
from app.modules.identity.dependencies import CurrentPlayer, PlayerWrites
from app.modules.lobby.schemas import Room
from app.modules.social import live
from app.modules.social.dependencies import RoomInvites
from app.modules.social.schemas import (
    InviteCode,
    InviteLink,
)

router = APIRouter()


@router.post(
    "/rooms/{room_id}/invites/{friend_id}", status_code=204, dependencies=PlayerWrites
)
async def invite_to_room(
    room_id: UUID, friend_id: UUID, player: CurrentPlayer, social: RoomInvites
) -> None:
    await limit(social.platform, "room_invite", str(player.profile.id), 20, 600)
    await social.invite_to_room(player.profile, room_id, friend_id)


@router.get("/invites/rooms")
async def room_invites(
    player: CurrentPlayer, social: RoomInvites
) -> list[live.RoomInvite]:
    return await social.room_invites(player.profile.id)


@router.post("/rooms/{room_id}/link", dependencies=PlayerWrites)
async def invite_link(
    room_id: UUID, request: Request, player: CurrentPlayer, social: RoomInvites
) -> InviteLink:
    """Create a one-hour invitation to join through the browser."""
    await limit(social.platform, "invite_link", str(player.profile.id), 10, 600)
    origin = f"{request.url.scheme}://{request.url.netloc}"
    return await social.invite_link(player.profile, room_id, origin)


@router.post("/invites/{code}/join", dependencies=PlayerWrites)
async def join_by_link(
    code: InviteCode, player: CurrentPlayer, social: RoomInvites
) -> Room:
    return await social.join_by_link(player.profile, code)
