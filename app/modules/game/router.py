from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import OptionalPlatform
from app.core.errors import ErrorResponse
from app.core.rate_limit import client_host, limit
from app.modules.game.dependencies import AccessToken, Practice
from app.modules.game.schemas import (
    GameUpdate,
    PracticeCreated,
    PracticeHint,
    PracticePlayRequest,
    PracticeRequest,
)
from app.modules.game.story_store import for_attempt

router = APIRouter(prefix="/api/v1/practice", tags=["Practice"])
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
    body: PracticeRequest, request: Request, response: Response, service: Practice
) -> PracticeCreated:
    response.headers["Cache-Control"] = "no-store"
    return service.create(body.seats, body.level, client_host(request))


@router.get("/{game_id}", responses=AUTH_ERRORS)
async def get_practice(
    game_id: UUID,
    platform: OptionalPlatform,
    response: Response,
    token: AccessToken,
    service: Practice,
) -> GameUpdate:
    response.headers["Cache-Control"] = "no-store"
    store = for_attempt(platform, game_id, token)
    if store is not None:
        return await store.snapshot(game_id, token)
    return await run_in_threadpool(service.snapshot, game_id, token)


@router.get("/{game_id}/hint", responses={**AUTH_ERRORS, 429: {"model": ErrorResponse}})
async def hint(
    game_id: UUID,
    platform: OptionalPlatform,
    response: Response,
    token: AccessToken,
    service: Practice,
) -> PracticeHint:
    """The engine's view of your current choices. Practice only."""
    response.headers["Cache-Control"] = "no-store"
    store = for_attempt(platform, game_id, token)
    if store is not None and platform is not None:
        await limit(platform, "story_hint", str(game_id), 10, 60)
        return await store.hint(game_id, token)
    return await run_in_threadpool(service.hint, game_id, token)


@router.post(
    "/{game_id}/plays",
    responses={**AUTH_ERRORS, 409: {"model": ErrorResponse}},
)
async def play(
    game_id: UUID,
    body: PracticePlayRequest,
    platform: OptionalPlatform,
    response: Response,
    token: AccessToken,
    service: Practice,
) -> GameUpdate:
    response.headers["Cache-Control"] = "no-store"
    store = for_attempt(platform, game_id, token)
    if store is not None:
        return await store.play(game_id, token, body)
    return await run_in_threadpool(service.play, game_id, token, body)
