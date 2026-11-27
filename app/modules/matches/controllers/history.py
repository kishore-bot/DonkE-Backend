from uuid import UUID

from fastapi import APIRouter, Response

from app.core.dependencies import PlatformDep
from app.modules.identity.dependencies import CurrentPlayer
from app.modules.matches import settlement
from app.modules.matches.schemas import MatchResult, PublicReplay, RecentMatch

router = APIRouter()


@router.get("/{game_id}/replay")
async def replay(
    game_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> PublicReplay:
    """Public events of a finished match. The opening deal is never sent."""
    return PublicReplay.of(
        await settlement.read_replay(platform, game_id, player.profile.id)
    )


@router.get("/{game_id}/result")
async def match_result(
    game_id: UUID, player: CurrentPlayer, platform: PlatformDep, response: Response
) -> MatchResult:
    """Read the authenticated participant's placement and settled rewards."""
    response.headers["Cache-Control"] = "no-store"
    return await settlement.read_result(platform, game_id, player.profile.id)


@router.get("/results/recent")
async def recent_results(
    player: CurrentPlayer, platform: PlatformDep, response: Response
) -> list[RecentMatch]:
    """List up to ten recent results for the authenticated participant."""
    response.headers["Cache-Control"] = "no-store"
    return await settlement.recent_results(platform, player.profile.id)
