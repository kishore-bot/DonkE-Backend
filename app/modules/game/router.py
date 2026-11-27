from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError, ErrorResponse
from app.core.rate_limit import client_host
from app.modules.game.schemas import (
    GameUpdate,
    PracticeCreated,
    PracticeHint,
    PracticePlayRequest,
    PracticeRequest,
)
from app.modules.game.service import PracticeService
from app.modules.game.story_store import for_attempt

router = APIRouter(prefix="/api/v1/practice", tags=["Practice"])
bearer = HTTPBearer(auto_error=False)


def get_service(request: Request) -> PracticeService:
    return request.app.state.practice


def get_access_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    if credentials is None:
        raise AppError(401, "auth_required", "A practice access token is required")
    return credentials.credentials


Service = Annotated[PracticeService, Depends(get_service)]
AccessToken = Annotated[str, Depends(get_access_token)]

AUTH_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.post(
    "",
    status_code=201,
    responses={
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def create_practice(
    body: PracticeRequest, request: Request, response: Response, service: Service
) -> PracticeCreated:
    response.headers["Cache-Control"] = "no-store"
    return service.create(body.seats, body.level, client_host(request))


@router.get("/{game_id}", responses=AUTH_ERRORS)
async def get_practice(
    game_id: UUID,
    request: Request,
    response: Response,
    token: AccessToken,
    service: Service,
) -> GameUpdate:
    response.headers["Cache-Control"] = "no-store"
    store = for_attempt(request.app.state.platform, game_id, token)
    if store is not None:
        return await store.snapshot(game_id, token)
    return await run_in_threadpool(service.snapshot, game_id, token)


@router.get("/{game_id}/hint", responses=AUTH_ERRORS)
async def hint(
    game_id: UUID,
    request: Request,
    response: Response,
    token: AccessToken,
    service: Service,
) -> PracticeHint:
    """The engine's view of your current choices. Practice only."""
    response.headers["Cache-Control"] = "no-store"
    store = for_attempt(request.app.state.platform, game_id, token)
    if store is not None:
        return await store.hint(game_id, token)
    return await run_in_threadpool(service.hint, game_id, token)


@router.post(
    "/{game_id}/plays",
    responses={**AUTH_ERRORS, 409: {"model": ErrorResponse}},
)
async def play(
    game_id: UUID,
    body: PracticePlayRequest,
    request: Request,
    response: Response,
    token: AccessToken,
    service: Service,
) -> GameUpdate:
    response.headers["Cache-Control"] = "no-store"
    store = for_attempt(request.app.state.platform, game_id, token)
    if store is not None:
        return await store.play(game_id, token, body)
    return await run_in_threadpool(service.play, game_id, token, body)
