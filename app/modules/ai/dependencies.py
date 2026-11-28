from typing import Annotated

from fastapi import Depends, Request

from app.core.dependencies import PlatformDep
from app.modules.ai.services.gateway import Gateway


async def get_gateway(request: Request, _: PlatformDep) -> Gateway:
    return request.app.state.gateway


AI = Annotated[Gateway, Depends(get_gateway)]
