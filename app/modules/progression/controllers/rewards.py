from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Response

from app.modules.identity.dependencies import CurrentPlayer, PlayerWrites
from app.modules.progression.dependencies import SeasonRewards
from app.modules.progression.schemas.gifts import SeasonGifts

router = APIRouter()

Sku = Annotated[str, Path(min_length=1, max_length=80)]


@router.get("/seasons/rewards")
async def season_rewards(
    player: CurrentPlayer, progress: SeasonRewards, response: Response
) -> list[SeasonGifts]:
    """List earned gifts from the active packed season and its recent predecessors."""
    response.headers["Cache-Control"] = "no-store"
    return await progress.gifts(player.profile.id)


@router.post("/seasons/{season_id}/tiers/{tier}/claim", dependencies=PlayerWrites)
async def claim_tier(
    season_id: UUID,
    tier: Annotated[int, Path(ge=1, le=30)],
    player: CurrentPlayer,
    progress: SeasonRewards,
) -> dict[str, bool]:
    return {"credited": await progress.claim(player.profile.id, season_id, tier=tier)}


@router.post("/seasons/{season_id}/weekly/{challenge}/claim", dependencies=PlayerWrites)
async def claim_weekly(
    season_id: UUID,
    challenge: Sku,
    player: CurrentPlayer,
    progress: SeasonRewards,
    week: date | None = None,
) -> dict[str, bool]:
    return {
        "credited": await progress.claim(
            player.profile.id, season_id, challenge=challenge, week=week
        )
    }


@router.post("/seasons/{season_id}/bonus/{tier}/claim", dependencies=PlayerWrites)
async def claim_bonus(
    season_id: UUID,
    tier: Annotated[int, Path(ge=1, le=4)],
    player: CurrentPlayer,
    progress: SeasonRewards,
) -> dict[str, bool]:
    return {"credited": await progress.claim(player.profile.id, season_id, bonus=tier)}
