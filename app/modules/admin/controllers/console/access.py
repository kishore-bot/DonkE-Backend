from fastapi import Response

from app.core.errors import AppError
from app.modules.admin.dependencies import Admin, Cookie
from app.modules.admin.schemas.auth import AdminProfile, Role
from app.modules.admin.services.admin import AdminService

STAFF: tuple[Role, ...] = ("viewer", "moderator", "admin")


MODERATORS: tuple[Role, ...] = ("moderator", "admin")


ADMINS: tuple[Role, ...] = ("admin",)


async def staff(
    admin: AdminService, cookie: str | None, roles: tuple[Role, ...]
) -> AdminProfile:
    identity = await admin.current(cookie)
    if identity.admin.role not in roles:
        raise AppError(403, "role_required", "Your admin role cannot do this")
    return identity.admin


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


async def require_staff(admin: Admin, cookie: Cookie) -> None:
    await staff(admin, cookie, STAFF)


async def require_moderator(admin: Admin, cookie: Cookie) -> None:
    await staff(admin, cookie, MODERATORS)


async def require_admin(admin: Admin, cookie: Cookie) -> None:
    await staff(admin, cookie, ADMINS)
