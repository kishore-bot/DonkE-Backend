from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.security import APIKeyCookie

from app.core.platform import Platform, get_platform
from app.core.rate_limit import client_host, limit
from app.modules.admin.schemas import AdminLogin, AuditEntry, Login
from app.modules.admin.service import AdminService

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])
SESSION_COOKIE = "__Host-donke-admin"
Cookie = Annotated[
    str | None, Depends(APIKeyCookie(name=SESSION_COOKIE, auto_error=False))
]
RequestId = Annotated[UUID | None, Header(alias="X-Request-ID")]
CsrfToken = Annotated[str | None, Header(alias="X-CSRF-Token", max_length=64)]
PlatformDep = Annotated[Platform, Depends(get_platform)]


def get_admin(request: Request, _: PlatformDep) -> AdminService:
    return request.app.state.admin


Admin = Annotated[AdminService, Depends(get_admin)]


@router.post("/auth/login")
async def login(
    body: Login,
    request: Request,
    response: Response,
    platform: PlatformDep,
    admin: Admin,
    request_id: RequestId = None,
) -> AdminLogin:
    await limit(platform, "admin_login_ip", client_host(request), 10, 60)
    await limit(platform, "admin_login_name", body.username, 5, 900)
    result, cookie = await admin.sign_in(
        body.username, body.password, request_id or uuid4()
    )
    response.set_cookie(
        SESSION_COOKIE,
        cookie,
        max_age=platform.settings.admin_session_seconds,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/auth/me")
async def current(cookie: Cookie, response: Response, admin: Admin) -> AdminLogin:
    response.headers["Cache-Control"] = "no-store"
    return await admin.current(cookie)


@router.post("/auth/logout", status_code=204)
async def logout(
    cookie: Cookie,
    response: Response,
    admin: Admin,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> None:
    await admin.logout(cookie, csrf, request_id or uuid4())
    response.delete_cookie(
        SESSION_COOKIE, secure=True, httponly=True, samesite="strict", path="/"
    )


@router.get("/audit")
async def audit(cookie: Cookie, response: Response, admin: Admin) -> list[AuditEntry]:
    response.headers["Cache-Control"] = "no-store"
    return await admin.audit(cookie)
