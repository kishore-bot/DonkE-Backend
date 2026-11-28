from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import APIKeyCookie

from app.core.dependencies import PlatformDep
from app.modules.admin.services.admin import AdminService

SESSION_COOKIE = "__Host-donke-admin"
Cookie = Annotated[
    str | None, Depends(APIKeyCookie(name=SESSION_COOKIE, auto_error=False))
]
RequestId = Annotated[UUID | None, Header(alias="X-Request-ID")]
CsrfToken = Annotated[str | None, Header(alias="X-CSRF-Token", max_length=64)]


async def get_admin(request: Request, _: PlatformDep) -> AdminService:
    return request.app.state.admin


Admin = Annotated[AdminService, Depends(get_admin)]
