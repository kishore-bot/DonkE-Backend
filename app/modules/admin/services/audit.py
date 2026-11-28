from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from secrets import compare_digest
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.platform import Platform
from app.core.tokens import token_digest
from app.modules.admin.models.admin_audit import AdminAudit
from app.modules.admin.repositories import admins


@asynccontextmanager
async def admin_write(
    platform: Platform,
    cookie: str | None,
    csrf: str | None,
    request_id: UUID | None,
    action: str,
    reason: str,
    roles: tuple[str, ...] = ("admin",),
) -> AsyncIterator[AsyncSession]:
    async with platform.sessions.begin() as db:
        row = await admins.session_owner(
            db, token_digest(cookie or ""), datetime.now(UTC), lock=True
        )
        if row is None:
            raise AppError(401, "invalid_admin_session", "Admin authentication failed")
        session, admin = row
        if admin.role not in roles:
            raise AppError(403, "admin_required", "Admin role required")
        if csrf is None or not compare_digest(
            csrf.encode(), session.csrf_token.encode()
        ):
            raise AppError(403, "csrf_required", "Send a valid CSRF token")
        db.add(
            AdminAudit(
                admin_id=admin.id,
                action=action,
                reason=reason,
                request_id=request_id or uuid4(),
            )
        )
        yield db
