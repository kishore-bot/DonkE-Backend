from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.modules.game.services.practice import PracticeService

bearer = HTTPBearer(auto_error=False)


async def get_service(request: Request) -> PracticeService:
    return request.app.state.practice


async def get_access_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    if credentials is None:
        raise AppError(401, "auth_required", "A practice access token is required")
    return credentials.credentials


Practice = Annotated[PracticeService, Depends(get_service)]
AccessToken = Annotated[str, Depends(get_access_token)]
