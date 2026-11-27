from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import PlatformDep
from app.core.rate_limit import limit
from app.modules.identity.google import GoogleIdentity
from app.modules.identity.service import IdentityService, Principal, unauthorized
from app.modules.social.live import touch

player_bearer = HTTPBearer(auto_error=False, scheme_name="PlayerAccess")
PlayerCredentials = Annotated[
    HTTPAuthorizationCredentials | None, Depends(player_bearer)
]


async def get_google(request: Request, _: PlatformDep) -> GoogleIdentity:
    return request.app.state.google


Google = Annotated[GoogleIdentity, Depends(get_google)]


async def optional_player(
    platform: PlatformDep, credentials: PlayerCredentials
) -> Principal | None:
    if credentials is None:
        return None
    principal = await IdentityService(platform).authenticate(credentials.credentials)
    # Authenticated requests keep the player online for friends.
    await touch(platform, principal.profile.id)
    return principal


OptionalPlayer = Annotated[Principal | None, Depends(optional_player)]


async def current_player(player: OptionalPlayer) -> Principal:
    if player is None:
        raise unauthorized()
    return player


CurrentPlayer = Annotated[Principal, Depends(current_player)]


async def limit_player_writes(player: CurrentPlayer, platform: PlatformDep) -> None:
    await limit(platform, "lobby_write", str(player.profile.id), 60, 60)


PlayerWrites = [Depends(limit_player_writes)]
