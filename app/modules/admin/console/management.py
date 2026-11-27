from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete, select

from app.core.dependencies import PlatformDep
from app.core.errors import AppError
from app.modules.admin import flags
from app.modules.admin.console.access import (
    ADMINS,
    no_store,
    require_admin,
    require_staff,
    staff,
)
from app.modules.admin.console.schemas import (
    AdminCreate,
    AdminRow,
    AdminUpdate,
    FlagUpdate,
    FlagView,
)
from app.modules.admin.dependencies import Admin, Cookie, CsrfToken, RequestId
from app.modules.admin.models import AdminSession, AdminUser
from app.modules.admin.schemas import AdminProfile
from app.modules.admin.service import admin_write

router = APIRouter()


@router.get("/flags", dependencies=[Depends(require_staff)])
async def list_flags(response: Response, platform: PlatformDep) -> list[FlagView]:
    no_store(response)
    values = await flags.current(platform)
    return [
        FlagView(key=key, value=values[key], description=spec.description)
        for key, spec in flags.FLAGS.items()
    ]


@router.put("/flags/{key}")
async def update_flag(
    key: str,
    body: FlagUpdate,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> FlagView:
    spec = flags.FLAGS.get(key)
    if spec is None:
        raise AppError(404, "flag_not_found", "Unknown runtime flag")
    async with admin_write(
        platform, cookie, csrf, request_id, f"flag_{key}"[:48], body.reason
    ) as db:
        await flags.set_flag(platform, db, key, body.value)
    # Committed: drop the cache and answer from Postgres, the source of truth.
    await flags.invalidate(platform)
    values = await flags.stored(platform)
    return FlagView(key=key, value=values[key], description=spec.description)


@router.get("/users", dependencies=[Depends(require_admin)])
async def admin_users(response: Response, platform: PlatformDep) -> list[AdminRow]:
    no_store(response)
    async with platform.sessions() as db:
        rows = await db.scalars(select(AdminUser).order_by(AdminUser.username))
        return [AdminRow.model_validate(row) for row in rows]


@router.post("/users", status_code=201)
async def create_admin_user(
    body: AdminCreate,
    cookie: Cookie,
    admin: Admin,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> AdminProfile:
    return await admin.create_console_account(
        body.username,
        body.password,
        body.role,
        cookie=cookie,
        csrf=csrf,
        request_id=request_id,
        reason=body.reason,
    )


@router.put("/users/{admin_id}")
async def update_admin_user(
    admin_id: UUID,
    body: AdminUpdate,
    platform: PlatformDep,
    cookie: Cookie,
    admin: Admin,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> AdminRow:
    me = await staff(admin, cookie, ADMINS)
    if admin_id == me.id and (body.active is False or body.role not in {None, "admin"}):
        raise AppError(
            409, "cannot_demote_self", "Ask another admin to change your access"
        )
    async with admin_write(
        platform, cookie, csrf, request_id, "update_admin", body.reason
    ) as db:
        user = await db.get(AdminUser, admin_id, with_for_update=True)
        if user is None:
            raise AppError(404, "admin_not_found", "Admin account not found")
        if body.role is not None:
            user.role = body.role
        if body.active is not None:
            user.active = body.active
        if body.active is False:
            # Sign out everywhere now; re-enabling the account later must
            # require a fresh sign-in, not revive these sessions.
            await db.execute(
                delete(AdminSession).where(AdminSession.admin_id == admin_id)
            )
        await db.flush()
        return AdminRow.model_validate(user)
