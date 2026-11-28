from uuid import UUID

from fastapi import APIRouter

from app.modules.identity.dependencies import CurrentPlayer, PlayerWrites
from app.modules.lobby.schemas.queue import QueueStatus
from app.modules.social.dependencies import Parties
from app.modules.social.schemas.parties import PartyView

router = APIRouter()


@router.post("/parties", dependencies=PlayerWrites)
async def create_party(player: CurrentPlayer, social: Parties) -> PartyView:
    return await social.create_party(player.profile.id)


@router.get("/parties/me")
async def my_party(player: CurrentPlayer, social: Parties) -> PartyView:
    return await social.my_party(player.profile.id)


@router.get("/parties/invites")
async def invites(player: CurrentPlayer, social: Parties) -> list[UUID]:
    return await social.invites(player.profile.id)


@router.post("/parties/invite/{player_id}", status_code=204, dependencies=PlayerWrites)
async def invite(player_id: UUID, player: CurrentPlayer, social: Parties) -> None:
    await social.invite(player.profile.id, player_id)


@router.post("/parties/{party_id}/join", dependencies=PlayerWrites)
async def join_party(
    party_id: UUID, player: CurrentPlayer, social: Parties
) -> PartyView:
    return await social.accept_invite(player.profile.id, party_id)


@router.post("/parties/leave", status_code=204, dependencies=PlayerWrites)
async def leave_party(player: CurrentPlayer, social: Parties) -> None:
    await social.leave(player.profile.id)


@router.post("/parties/queue", dependencies=PlayerWrites)
async def queue_party(player: CurrentPlayer, social: Parties) -> QueueStatus:
    return await social.queue(player.profile.id)
