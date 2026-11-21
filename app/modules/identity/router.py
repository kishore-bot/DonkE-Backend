from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.platform import Platform, get_platform
from app.core.rate_limit import client_host, limit
from app.modules.identity.google import GoogleIdentity
from app.modules.identity.schemas import (
    GoogleSignIn,
    Profile,
    ProfileUpdate,
    RefreshRequest,
    SessionTokens,
)
from app.modules.identity.service import IdentityService, Principal, unauthorized
from app.modules.social.live import touch

router = APIRouter(prefix="/api/v1/auth", tags=["Identity"])
PlatformDep = Annotated[Platform, Depends(get_platform)]
bearer = HTTPBearer(auto_error=False, scheme_name="PlayerAccess")


def get_google(request: Request) -> GoogleIdentity:
    return request.app.state.google


async def current_player(
    platform: PlatformDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None:
        raise unauthorized()
    principal = await IdentityService(platform).authenticate(credentials.credentials)
    # Any authenticated request keeps the player "online" for friends.
    await touch(platform, principal.profile.id)
    return principal


CurrentPlayer = Annotated[Principal, Depends(current_player)]


@router.post("/google")
async def google_sign_in(
    body: GoogleSignIn,
    request: Request,
    response: Response,
    platform: PlatformDep,
    verifier: Annotated[GoogleIdentity, Depends(get_google)],
) -> SessionTokens:
    await limit(platform, "google", client_host(request), 15, 60)
    response.headers["Cache-Control"] = "no-store"
    return await IdentityService(platform).sign_in(await verifier.verify(body.id_token))


@router.post("/refresh")
async def refresh(
    body: RefreshRequest, request: Request, response: Response, platform: PlatformDep
) -> SessionTokens:
    await limit(platform, "refresh", client_host(request), 60, 60)
    response.headers["Cache-Control"] = "no-store"
    return await IdentityService(platform).refresh(body.refresh_token)


@router.get("/me")
async def profile(principal: CurrentPlayer) -> Profile:
    return principal.profile


@router.patch("/me")
async def update_profile(
    body: ProfileUpdate, principal: CurrentPlayer, platform: PlatformDep
) -> Profile:
    return await IdentityService(platform).update_profile(principal, body)


@router.post("/logout", status_code=204)
async def logout(principal: CurrentPlayer, platform: PlatformDep) -> None:
    await IdentityService(platform).logout(principal)
