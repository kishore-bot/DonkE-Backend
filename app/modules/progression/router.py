from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response

from app.modules.admin.router import Cookie, CsrfToken, RequestId
from app.modules.admin.service import admin_write
from app.modules.identity.router import CurrentPlayer, PlatformDep
from app.modules.lobby.router import Writes
from app.modules.matches.repository import MatchRepository
from app.modules.matches.settlement import read_replay
from app.modules.progression import service, squad
from app.modules.progression.analytics import MatchAnalytics, match_analytics
from app.modules.progression.schemas import (
    AchievementsView,
    CatalogItem,
    CloseSeason,
    MySeason,
    SeasonCreate,
    SeasonGifts,
    SeasonInfo,
    Standing,
    WalletView,
)
from app.modules.progression.service import ProgressionService
from app.modules.progression.season_content import (
    CharacterSelection,
    SeasonManifest,
    SelectCharacter,
)

router = APIRouter(prefix="/api/v1", tags=["Progression"])
Sku = Annotated[str, Path(min_length=1, max_length=80)]


def progression(platform: PlatformDep) -> ProgressionService:
    return ProgressionService(platform)


Progression = Annotated[ProgressionService, Depends(progression)]


@router.get("/store/wallet")
async def balance(player: CurrentPlayer, progress: Progression) -> WalletView:
    return WalletView(coins=await progress.balance(player.profile.id))


@router.get("/store/catalog")
async def catalog(player: CurrentPlayer, progress: Progression) -> list[CatalogItem]:
    return await progress.catalog(player.profile.id)


@router.get("/store/inventory")
async def inventory(player: CurrentPlayer, progress: Progression) -> list[str]:
    return await progress.inventory(player.profile.id)


@router.post("/store/{sku}/buy", dependencies=Writes)
async def buy(sku: Sku, player: CurrentPlayer, progress: Progression) -> WalletView:
    return WalletView(coins=await progress.buy(player.profile.id, sku))


@router.put("/store/{sku}/equip", status_code=204, dependencies=Writes)
async def equip(sku: Sku, player: CurrentPlayer, progress: Progression) -> None:
    await progress.equip(player.profile.id, sku)


@router.get("/seasons/current")
async def current(player: CurrentPlayer, progress: Progression) -> MySeason | None:
    return await progress.current(player.profile.id)


@router.get("/seasons/rewards")
async def season_rewards(
    player: CurrentPlayer, progress: Progression, response: Response
) -> list[SeasonGifts]:
    """List earned gifts from the active packed season and its recent predecessors."""
    response.headers["Cache-Control"] = "no-store"
    return await progress.gifts(player.profile.id)


@router.get("/seasons/squads")
async def season_squads(
    player: CurrentPlayer, platform: PlatformDep, response: Response
) -> squad.SquadOverview:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions() as db:
        return await squad.overview(db, player.profile.id, datetime.now(UTC))


@router.post("/seasons/{season_id}/squad", dependencies=Writes)
async def enroll_squad(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> squad.SquadProgress:
    async with platform.sessions.begin() as db:
        return await squad.enroll(db, season_id, player.profile.id, datetime.now(UTC))


@router.post("/seasons/{season_id}/squad/claim", dependencies=Writes)
async def claim_squad(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> squad.SquadProgress:
    async with platform.sessions.begin() as db:
        return await squad.claim(db, season_id, player.profile.id, datetime.now(UTC))


@router.get("/seasons/active/manifest")
async def season_manifest(
    request: Request, response: Response
) -> SeasonManifest | None:
    """The published cast and schedule for guests and signed-in players."""
    response.headers["Cache-Control"] = "no-store"
    platform = request.app.state.platform
    if platform is None:
        return None
    async with platform.sessions() as db:
        return await service.active_manifest(db, datetime.now(UTC))


@router.get("/seasons/{season_id}/me/character")
async def selected_character(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep, response: Response
) -> CharacterSelection:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions() as db:
        return await service.season_character(
            db, season_id, player.profile.id, datetime.now(UTC)
        )


@router.put("/seasons/{season_id}/me/character", dependencies=Writes)
async def choose_character(
    season_id: UUID, body: SelectCharacter, player: CurrentPlayer, platform: PlatformDep
) -> CharacterSelection:
    async with platform.sessions.begin() as db:
        return await service.season_character(
            db,
            season_id,
            player.profile.id,
            datetime.now(UTC),
            character_id=body.character_id,
        )


@router.get("/seasons/{season_id}/board")
async def board(
    season_id: UUID, _: CurrentPlayer, progress: Progression
) -> list[Standing]:
    return await progress.board(season_id)


@router.post("/seasons/{season_id}/tiers/{tier}/claim", dependencies=Writes)
async def claim_tier(
    season_id: UUID,
    tier: Annotated[int, Path(ge=1, le=30)],
    player: CurrentPlayer,
    progress: Progression,
) -> dict[str, bool]:
    return {"credited": await progress.claim(player.profile.id, season_id, tier=tier)}


@router.post("/seasons/{season_id}/weekly/{challenge}/claim", dependencies=Writes)
async def claim_weekly(
    season_id: UUID,
    challenge: Sku,
    player: CurrentPlayer,
    progress: Progression,
    week: date | None = None,
) -> dict[str, bool]:
    return {
        "credited": await progress.claim(
            player.profile.id, season_id, challenge=challenge, week=week
        )
    }


@router.post("/seasons/{season_id}/bonus/{tier}/claim", dependencies=Writes)
async def claim_bonus(
    season_id: UUID,
    tier: Annotated[int, Path(ge=1, le=4)],
    player: CurrentPlayer,
    progress: Progression,
) -> dict[str, bool]:
    return {"credited": await progress.claim(player.profile.id, season_id, bonus=tier)}


@router.get("/achievements")
async def achievements(
    player: CurrentPlayer, progress: Progression
) -> AchievementsView:
    return await progress.achievements(player.profile.id)


@router.get("/games/{game_id}/analytics")
async def analytics(
    game_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> MatchAnalytics:
    return match_analytics(await read_replay(platform, game_id, player.profile.id))


@router.post("/admin/seasons", status_code=201)
async def create_season(
    body: SeasonCreate,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> SeasonInfo:
    async with admin_write(
        platform, cookie, csrf, request_id, "create_season", body.reason
    ) as db:
        return await service.create_season(db, body)


@router.post("/admin/seasons/{season_id}/close")
async def close_season(
    season_id: UUID,
    body: CloseSeason,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> SeasonInfo:
    async with admin_write(
        platform, cookie, csrf, request_id, "close_season", body.reason
    ) as db:
        return await service.close_season(
            db, MatchRepository(platform), season_id, datetime.now(UTC)
        )
