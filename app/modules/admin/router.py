from uuid import uuid4

from fastapi import APIRouter, Request, Response

from app.core.dependencies import PlatformDep
from app.core.rate_limit import client_host, limit
from app.modules.admin.dependencies import (
    SESSION_COOKIE,
    Admin,
    Cookie,
    CsrfToken,
    RequestId,
)
from app.modules.admin.schemas import (
    AdminLogin,
    AdminProfile,
    AuditEntry,
    Login,
    TotpCode,
    TotpSetup,
)

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


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
        body.username, body.password, request_id or uuid4(), body.totp
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


@router.post("/auth/totp/setup")
async def totp_setup(
    cookie: Cookie, response: Response, admin: Admin, csrf: CsrfToken = None
) -> TotpSetup:
    """Start two-factor setup; scan the URI, then confirm with a code."""
    response.headers["Cache-Control"] = "no-store"
    return await admin.totp_setup(cookie, csrf)


@router.post("/auth/totp/confirm")
async def totp_confirm(
    body: TotpCode,
    cookie: Cookie,
    admin: Admin,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> AdminProfile:
    return await admin.totp_confirm(cookie, csrf, body.code, request_id or uuid4())


@router.get("/audit")
async def audit(cookie: Cookie, response: Response, admin: Admin) -> list[AuditEntry]:
    response.headers["Cache-Control"] = "no-store"
    return await admin.audit(cookie)
