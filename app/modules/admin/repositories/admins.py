from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models.admin_audit import AdminAudit
from app.modules.admin.models.admin_session import AdminSession
from app.modules.admin.models.admin_user import AdminUser


async def by_username(db: AsyncSession, username: str) -> AdminUser | None:
    return await db.scalar(select(AdminUser).where(AdminUser.username == username))


async def session_owner(
    db: AsyncSession, digest: bytes, now: datetime, *, lock: bool = False
) -> tuple[AdminSession, AdminUser] | None:
    query = (
        select(AdminSession, AdminUser)
        .join(AdminUser, AdminUser.id == AdminSession.admin_id)
        .where(
            AdminSession.token_digest == digest,
            AdminSession.expires_at > now,
            AdminUser.active.is_(True),
        )
    )
    if lock:
        query = query.with_for_update(of=AdminSession)
    row = (await db.execute(query)).one_or_none()
    return (row[0], row[1]) if row is not None else None


async def recent_audit(db: AsyncSession) -> list[AdminAudit]:
    result = await db.scalars(
        select(AdminAudit).order_by(AdminAudit.at.desc(), AdminAudit.id).limit(50)
    )
    return list(result)


async def prune_expired(db: AsyncSession, now: datetime) -> None:
    await db.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
