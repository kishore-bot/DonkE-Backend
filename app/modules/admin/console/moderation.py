from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.core.dependencies import PlatformDep
from app.core.errors import AppError
from app.modules.admin.console.access import (
    MODERATORS,
    no_store,
    require_moderator,
)
from app.modules.admin.console.schemas import (
    MuteRequest,
    ReportResolve,
)
from app.modules.admin.dependencies import Cookie, CsrfToken, RequestId
from app.modules.admin.service import admin_write
from app.modules.identity.models import Player
from app.modules.social.models import PlayerMute, PlayerReport
from app.modules.social.schemas import ReportView

router = APIRouter()


@router.post("/players/{player_id}/mute")
async def mute(
    player_id: UUID,
    body: MuteRequest,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> dict[str, datetime | None]:
    """Chat mute; the player can still play. `minutes: 0` lifts it."""
    action = "unmute_player" if body.minutes == 0 else "mute_player"
    async with admin_write(
        platform, cookie, csrf, request_id, action, body.reason, roles=MODERATORS
    ) as db:
        if await db.get(Player, player_id) is None:
            raise AppError(404, "player_not_found", "Player not found")
        row = await db.get(PlayerMute, player_id, with_for_update=True)
        if body.minutes == 0:
            if row is not None:
                await db.delete(row)
            return {"muted_until": None}
        until = datetime.now(UTC) + timedelta(minutes=body.minutes)
        if row is None:
            db.add(PlayerMute(player_id=player_id, until=until, reason=body.reason))
        else:
            row.until, row.reason = until, body.reason
        return {"muted_until": until}


@router.get("/reports", dependencies=[Depends(require_moderator)])
async def reports(
    response: Response,
    platform: PlatformDep,
    status: Literal["open", "dismissed", "actioned"] = "open",
) -> list[ReportView]:
    no_store(response)
    async with platform.sessions() as db:
        rows = await db.scalars(
            select(PlayerReport)
            .where(PlayerReport.status == status)
            .order_by(PlayerReport.created_at.desc())
            .limit(100)
        )
        return [ReportView.model_validate(row) for row in rows]


@router.post("/reports/{report_id}/resolve")
async def resolve_report(
    report_id: UUID,
    body: ReportResolve,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> ReportView:
    async with admin_write(
        platform,
        cookie,
        csrf,
        request_id,
        f"report_{body.decision}",
        body.reason,
        roles=MODERATORS,
    ) as db:
        report = await db.get(PlayerReport, report_id, with_for_update=True)
        if report is None:
            raise AppError(404, "report_not_found", "Report not found")
        if report.status == "open":
            report.status = body.decision
            report.resolution = body.reason
            report.resolved_at = datetime.now(UTC)
        await db.flush()
        return ReportView.model_validate(report)
