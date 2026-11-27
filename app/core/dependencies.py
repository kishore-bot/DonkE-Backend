from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.core.platform import Platform


async def get_optional_platform(request: Request) -> Platform | None:
    return request.app.state.platform


OptionalPlatform = Annotated[Platform | None, Depends(get_optional_platform)]


async def get_platform(platform: OptionalPlatform) -> Platform:
    if platform is None:
        raise AppError(503, "online_unavailable", "Online play is unavailable")
    return platform


PlatformDep = Annotated[Platform, Depends(get_platform)]
