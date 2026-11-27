from typing import Annotated

from fastapi import Depends

from app.core.dependencies import PlatformDep
from app.modules.progression.services.player_progress import SeasonProgressService
from app.modules.progression.services.season_rewards import SeasonRewardsService
from app.modules.progression.services.store import StoreService


async def get_store(platform: PlatformDep) -> StoreService:
    return StoreService(platform)


async def get_season_progress(platform: PlatformDep) -> SeasonProgressService:
    return SeasonProgressService(platform)


async def get_season_rewards(platform: PlatformDep) -> SeasonRewardsService:
    return SeasonRewardsService(platform)


Store = Annotated[StoreService, Depends(get_store)]
SeasonProgress = Annotated[SeasonProgressService, Depends(get_season_progress)]
SeasonRewards = Annotated[SeasonRewardsService, Depends(get_season_rewards)]
