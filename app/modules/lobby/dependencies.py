from typing import Annotated

from fastapi import Depends

from app.core.dependencies import PlatformDep
from app.modules.lobby.repositories.lobby import LobbyRepository
from app.modules.lobby.services.lobby import LobbyService


async def get_lobby(platform: PlatformDep) -> LobbyService:
    return LobbyService(LobbyRepository(platform.redis, platform.settings))


Lobby = Annotated[LobbyService, Depends(get_lobby)]
