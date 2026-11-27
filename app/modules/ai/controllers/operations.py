from typing import Literal
from uuid import UUID

from fastapi import APIRouter

from app.core.dependencies import PlatformDep
from app.core.errors import AppError
from app.modules.admin.dependencies import Admin, Cookie, CsrfToken, RequestId
from app.modules.admin.service import admin_write
from app.modules.ai.dependencies import AI
from app.modules.ai.fair_play import CaseView, Resolve, cases, resolve
from app.modules.ai.index import reindex
from app.modules.ai.schemas import (
    ReindexRequest,
)

router = APIRouter()


@router.get("/admin/fair-play")
async def fair_play_cases(
    admin: Admin,
    cookie: Cookie,
    platform: PlatformDep,
    status: Literal["open", "dismissed", "confirmed"] = "open",
) -> list[CaseView]:
    identity = await admin.current(cookie)
    if identity.admin.role not in {"moderator", "admin"}:
        raise AppError(403, "moderator_required", "Moderator role required")
    return await cases(platform, status)


@router.post("/admin/fair-play/{case_id}/resolve")
async def resolve_case(
    case_id: UUID,
    body: Resolve,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> CaseView:
    """A moderator decides; the engine only flags."""
    async with admin_write(
        platform,
        cookie,
        csrf,
        request_id,
        f"fair_play_{body.decision}",
        body.reason,
        roles=("moderator", "admin"),
    ) as db:
        return await resolve(db, case_id, body)


@router.get("/admin/ai/usage")
async def usage(admin: Admin, cookie: Cookie, gateway: AI) -> dict[str, int]:
    identity = await admin.current(cookie)
    if identity.admin.role != "admin":
        raise AppError(403, "admin_required", "Admin role required")
    return await gateway.usage()


@router.post("/admin/ai/reindex")
async def sync_index(
    body: ReindexRequest,
    platform: PlatformDep,
    cookie: Cookie,
    gateway: AI,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> dict[str, int]:
    async with admin_write(
        platform, cookie, csrf, request_id, "reindex_rules", body.reason
    ) as db:
        return {"indexed": await reindex(gateway, db)}
