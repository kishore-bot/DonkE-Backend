from uuid import UUID

from fastapi import APIRouter, Response

from app.core.dependencies import PlatformDep
from app.modules.identity.dependencies import CurrentPlayer
from app.modules.matches.repositories import history
from app.modules.matches.schemas.results import MatchResult, PublicReplay, RecentMatch
from app.modules.matches.services import results

router = APIRouter()


@router.get("/{game_id}/replay")
async def replay(
    game_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> PublicReplay:
    """Public events of a finished match. The opening deal is never sent."""
    return PublicReplay.of(
        await history.read_replay(platform, game_id, player.profile.id)
    )


@router.get("/{game_id}/result")
async def match_result(
    game_id: UUID, player: CurrentPlayer, platform: PlatformDep, response: Response
) -> MatchResult:
    """Read the authenticated participant's placement and settled rewards."""
    response.headers["Cache-Control"] = "no-store"
    return await results.read_result(platform, game_id, player.profile.id)


@router.get("/results/recent")
async def recent_results(
    player: CurrentPlayer, platform: PlatformDep, response: Response
) -> list[RecentMatch]:
    """List up to ten recent results for the authenticated participant."""
    response.headers["Cache-Control"] = "no-store"
    return await history.recent_results(platform, player.profile.id)
