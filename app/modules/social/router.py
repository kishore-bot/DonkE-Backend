from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.modules.identity.router import CurrentPlayer, PlatformDep
from app.modules.lobby.router import Writes
from app.modules.lobby.schemas import QueueStatus
from app.modules.social.schemas import FriendStatus, PartyView
from app.modules.social.service import SocialService

router = APIRouter(prefix="/api/v1", tags=["Social"])


def get_social(platform: PlatformDep) -> SocialService:
    return SocialService(platform)


Social = Annotated[SocialService, Depends(get_social)]


@router.get("/friends")
async def friends(player: CurrentPlayer, social: Social) -> list[FriendStatus]:
    return await social.friends(player.profile.id)


@router.post("/friends/{player_id}", status_code=204, dependencies=Writes)
async def friend_request(
    player_id: UUID, player: CurrentPlayer, social: Social
) -> None:
    await social.request(player.profile.id, player_id)


@router.put("/friends/{player_id}", status_code=204, dependencies=Writes)
async def accept(player_id: UUID, player: CurrentPlayer, social: Social) -> None:
    await social.update_friend(player.profile.id, player_id, accept=True)


@router.delete("/friends/{player_id}", status_code=204, dependencies=Writes)
async def remove(player_id: UUID, player: CurrentPlayer, social: Social) -> None:
    await social.update_friend(player.profile.id, player_id, accept=False)


@router.post("/parties", dependencies=Writes)
async def create_party(player: CurrentPlayer, social: Social) -> PartyView:
    return await social.create_party(player.profile.id)


@router.get("/parties/me")
async def my_party(player: CurrentPlayer, social: Social) -> PartyView:
    return await social.my_party(player.profile.id)


@router.get("/parties/invites")
async def invites(player: CurrentPlayer, social: Social) -> list[UUID]:
    return await social.invites(player.profile.id)


@router.post("/parties/invite/{player_id}", status_code=204, dependencies=Writes)
async def invite(player_id: UUID, player: CurrentPlayer, social: Social) -> None:
    await social.invite(player.profile.id, player_id)


@router.post("/parties/{party_id}/join", dependencies=Writes)
async def join_party(
    party_id: UUID, player: CurrentPlayer, social: Social
) -> PartyView:
    return await social.accept_invite(player.profile.id, party_id)


@router.post("/parties/leave", status_code=204, dependencies=Writes)
async def leave_party(player: CurrentPlayer, social: Social) -> None:
    await social.leave(player.profile.id)


@router.post("/parties/queue", dependencies=Writes)
async def queue_party(player: CurrentPlayer, social: Social) -> QueueStatus:
    return await social.queue(player.profile.id)
