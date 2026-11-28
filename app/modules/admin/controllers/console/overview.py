from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select

from app.core.dependencies import PlatformDep
from app.core.errors import AppError
from app.modules.admin.controllers.console.access import no_store, require_staff
from app.modules.admin.helpers.match_rows import match_row
from app.modules.admin.schemas.console_views import Dashboard, MatchRow, StoreItem
from app.modules.admin.services import flags
from app.modules.ai.dependencies import AI
from app.modules.ai.models.fair_play_case import FairPlayCase
from app.modules.identity.models.player import Player
from app.modules.matches.models.match_record import MatchRecord
from app.modules.matches.schemas.results import MatchReplay
from app.modules.progression.helpers.catalog import CATALOG, in_window
from app.modules.progression.models.cosmetic import Cosmetic
from app.modules.progression.models.season import Season
from app.modules.progression.schemas.analytics import MatchAnalytics
from app.modules.progression.schemas.seasons import SeasonInfo
from app.modules.progression.services.analytics import match_analytics

router = APIRouter()


@router.get("/dashboard", dependencies=[Depends(require_staff)])
async def dashboard(
    gateway: AI,
    response: Response,
    platform: PlatformDep,
) -> Dashboard:
    no_store(response)
    since = datetime.now(UTC) - timedelta(days=1)
    async with platform.sessions() as db:
        players = await db.scalar(select(func.count()).select_from(Player)) or 0
        new = await db.scalar(select(func.count()).where(Player.created_at >= since))
        matches = await db.scalar(
            select(func.count()).where(MatchRecord.finished_at >= since)
        )
        cases = await db.scalar(
            select(func.count()).where(FairPlayCase.status == "open")
        )
    active = await platform.redis.zcard(
        f"{platform.settings.redis_prefix}:game:index:turns"
    )
    return Dashboard(
        players=players,
        new_players_24h=new or 0,
        matches_24h=matches or 0,
        active_games=active,
        open_fair_play_cases=cases or 0,
        ai_usage=await gateway.usage(),
        flags=await flags.current(platform),
    )


@router.get("/matches", dependencies=[Depends(require_staff)])
async def matches(
    response: Response,
    platform: PlatformDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[MatchRow]:
    no_store(response)
    async with platform.sessions() as db:
        records = await db.scalars(
            select(MatchRecord).order_by(MatchRecord.finished_at.desc()).limit(limit)
        )
        return [match_row(record) for record in records]


@router.get("/matches/{game_id}", dependencies=[Depends(require_staff)])
async def match_detail(
    game_id: UUID,
    response: Response,
    platform: PlatformDep,
) -> MatchAnalytics:
    no_store(response)
    async with platform.sessions() as db:
        record = await db.get(MatchRecord, game_id)
    if record is None:
        raise AppError(404, "game_not_found", "Match not found")
    return match_analytics(MatchReplay.model_validate(record.replay))


@router.get("/store", dependencies=[Depends(require_staff)])
async def store(response: Response, platform: PlatformDep) -> list[StoreItem]:
    no_store(response)
    async with platform.sessions() as db:
        owners = dict(
            (
                await db.execute(
                    select(Cosmetic.sku, func.count()).group_by(Cosmetic.sku)
                )
            ).all()
        )
    today = datetime.now(UTC).date()
    return [
        StoreItem(
            sku=sku,
            label=item.label,
            slot=item.slot,
            price=item.price,
            festival=item.festival,
            available=in_window(item.window, today),
            owners=owners.get(sku, 0),
        )
        for sku, item in CATALOG.items()
    ]


@router.get("/seasons", dependencies=[Depends(require_staff)])
async def seasons(response: Response, platform: PlatformDep) -> list[SeasonInfo]:
    no_store(response)
    async with platform.sessions() as db:
        rows = await db.scalars(
            select(Season).order_by(Season.starts_at.desc()).limit(50)
        )
        return [SeasonInfo.model_validate(row) for row in rows]
