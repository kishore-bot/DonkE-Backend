from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Player, PlayerSession, RefreshToken


async def find_or_create_player(db: AsyncSession, subject: str) -> Player:
    player_id = uuid4()
    query = insert(Player).values(
        id=player_id, google_sub=subject, display_name=f"Player {player_id.hex[:8]}"
    )
    await db.execute(query.on_conflict_do_nothing(index_elements=[Player.google_sub]))
    return (await db.scalars(select(Player).where(Player.google_sub == subject))).one()


async def active_player(
    db: AsyncSession, player_id: UUID, session_id: UUID, at: datetime
) -> Player | None:
    query = (
        select(Player)
        .join(PlayerSession, Player.id == PlayerSession.player_id)
        .where(
            Player.id == player_id,
            Player.active.is_(True),
            PlayerSession.id == session_id,
            PlayerSession.revoked_at.is_(None),
            PlayerSession.expires_at > at,
        )
    )
    return await db.scalar(query)


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


async def prune_expired(db: AsyncSession, now: datetime) -> None:
    await db.execute(delete(PlayerSession).where(PlayerSession.expires_at <= now))
