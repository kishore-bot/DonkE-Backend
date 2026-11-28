from uuid import UUID

from fastapi import APIRouter

from app.core.dependencies import PlatformDep
from app.modules.identity.dependencies import CurrentPlayer
from app.modules.matches.repositories.history import read_replay
from app.modules.progression.dependencies import SeasonProgress
from app.modules.progression.schemas.achievements import AchievementsView
from app.modules.progression.schemas.analytics import MatchAnalytics
from app.modules.progression.services.analytics import match_analytics

router = APIRouter()


@router.get("/achievements")
async def achievements(
    player: CurrentPlayer, progress: SeasonProgress
) -> AchievementsView:
    return await progress.achievements(player.profile.id)


@router.get("/games/{game_id}/analytics")
async def analytics(
    game_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> MatchAnalytics:
    return match_analytics(await read_replay(platform, game_id, player.profile.id))
