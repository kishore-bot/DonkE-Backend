from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError, ErrorResponse
from app.modules.game.schemas import (
    GameUpdate,
    PlayRequest,
    PracticeCreated,
    PracticeRequest,
)
from app.modules.game.service import PracticeService

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
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def create_practice(
    body: PracticeRequest, response: Response, service: Service
) -> PracticeCreated:
    response.headers["Cache-Control"] = "no-store"
    return service.create(body.seats)


@router.get("/{game_id}", responses=AUTH_ERRORS)
def get_practice(
    game_id: UUID, response: Response, token: AccessToken, service: Service
) -> GameUpdate:
    response.headers["Cache-Control"] = "no-store"
    return service.snapshot(game_id, token)


@router.post(
    "/{game_id}/plays",
    responses={**AUTH_ERRORS, 409: {"model": ErrorResponse}},
)
def play(
    game_id: UUID,
    body: PlayRequest,
    response: Response,
    token: AccessToken,
    service: Service,
) -> GameUpdate:
    response.headers["Cache-Control"] = "no-store"
    return service.play(game_id, token, body)
