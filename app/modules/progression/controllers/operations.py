from uuid import UUID

from fastapi import APIRouter

from app.core.dependencies import PlatformDep
from app.modules.admin.dependencies import Cookie, CsrfToken, RequestId
from app.modules.admin.services.audit import admin_write
from app.modules.matches.repositories.matches import MatchRepository
from app.modules.progression.helpers.clock import utc_now
from app.modules.progression.schemas.seasons import (
    CloseSeason,
    SeasonCreate,
    SeasonInfo,
)
from app.modules.progression.services import seasons

router = APIRouter()


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
        return await seasons.create_season(db, body)


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
        return await seasons.close_season(
            db, MatchRepository(platform), season_id, utc_now()
        )
