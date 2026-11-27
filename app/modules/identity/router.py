from fastapi import APIRouter, Request, Response

from app.core.dependencies import PlatformDep
from app.core.rate_limit import client_host, limit
from app.modules.identity.dependencies import CurrentPlayer, Google
from app.modules.identity.schemas import (
    GoogleSignIn,
    Profile,
    ProfileUpdate,
    RefreshRequest,
    SessionTokens,
)
from app.modules.identity.service import IdentityService

router = APIRouter(prefix="/api/v1/auth", tags=["Identity"])


@router.post("/google")
async def google_sign_in(
    body: GoogleSignIn,
    request: Request,
    response: Response,
    platform: PlatformDep,
    verifier: Google,
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
