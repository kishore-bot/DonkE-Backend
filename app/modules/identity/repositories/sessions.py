from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models.player_session import PlayerSession
from app.modules.identity.models.refresh_token import RefreshToken


async def locked_session(db: AsyncSession, session_id: UUID) -> PlayerSession | None:
    return await db.scalar(
        select(PlayerSession).where(PlayerSession.id == session_id).with_for_update()
    )


async def lookup_token(
    db: AsyncSession, session_id: UUID, digest: bytes
) -> RefreshToken | None:
    return await db.scalar(
        select(RefreshToken).where(
            RefreshToken.session_id == session_id, RefreshToken.digest == digest
        )
    )


async def consume_outstanding(db: AsyncSession, session_id: UUID, at: datetime) -> None:
    """Mark every unused refresh token of a locked session as used."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.session_id == session_id, RefreshToken.used_at.is_(None))
        .values(used_at=at)
    )


async def prune_expired(db: AsyncSession, now: datetime) -> None:
    await db.execute(delete(PlayerSession).where(PlayerSession.expires_at <= now))
