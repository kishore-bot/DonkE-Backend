from uuid import UUID

from fastapi import APIRouter

from app.core.rate_limit import limit
from app.modules.identity.dependencies import CurrentPlayer, PlayerWrites
from app.modules.social.dependencies import Friends
from app.modules.social.schemas import (
    FriendStatus,
    Together,
)

router = APIRouter()


@router.get("/friends")
async def friends(player: CurrentPlayer, social: Friends) -> list[FriendStatus]:
    return await social.friends(player.profile.id)


@router.post("/friends/{player_id}", status_code=204, dependencies=PlayerWrites)
async def friend_request(
    player_id: UUID, player: CurrentPlayer, social: Friends
) -> None:
    await social.request(player.profile.id, player_id)


@router.put("/friends/{player_id}", status_code=204, dependencies=PlayerWrites)
async def accept(player_id: UUID, player: CurrentPlayer, social: Friends) -> None:
    await social.update_friend(player.profile.id, player_id, accept=True)


@router.delete("/friends/{player_id}", status_code=204, dependencies=PlayerWrites)
async def remove(player_id: UUID, player: CurrentPlayer, social: Friends) -> None:
    await social.update_friend(player.profile.id, player_id, accept=False)


@router.get("/blocks")
async def blocks(player: CurrentPlayer, social: Friends) -> list[UUID]:
    return await social.blocks(player.profile.id)


@router.post("/blocks/{player_id}", status_code=204, dependencies=PlayerWrites)
async def block(player_id: UUID, player: CurrentPlayer, social: Friends) -> None:
    """Blocking also removes the friendship and pending invites."""
    await social.block(player.profile.id, player_id)


@router.delete("/blocks/{player_id}", status_code=204, dependencies=PlayerWrites)
async def unblock(player_id: UUID, player: CurrentPlayer, social: Friends) -> None:
    await social.unblock(player.profile.id, player_id)


@router.get("/friends/{player_id}/together")
async def together(player_id: UUID, player: CurrentPlayer, social: Friends) -> Together:
    await limit(social.platform, "together", str(player.profile.id), 30, 60)
    return await social.together(player.profile.id, player_id)
