from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Integer, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Player, PlayerSession, RefreshToken
from app.modules.identity.schemas import Profile


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


async def consume_outstanding(
    db: AsyncSession, session_id: UUID, at: datetime
) -> None:
    """Mark every unused refresh token of a locked session as used."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.session_id == session_id, RefreshToken.used_at.is_(None))
        .values(used_at=at)
    )


async def prune_expired(db: AsyncSession, now: datetime) -> None:
    await db.execute(delete(PlayerSession).where(PlayerSession.expires_at <= now))


async def apply_rating(db: AsyncSession, player_id: UUID, delta: int) -> int:
    before = await db.scalar(
        select(Player.mmr).where(Player.id == player_id).with_for_update()
    )
    if before is None:
        return 0
    after = max(0, before + delta)
    await db.execute(update(Player).where(Player.id == player_id).values(mmr=after))
    return after - before


async def profiles(db: AsyncSession, player_ids: list[UUID]) -> dict[UUID, Profile]:
    rows = await db.scalars(
        select(Player)
        .where(Player.id.in_(player_ids), Player.active.is_(True))
        .order_by(Player.id)
    )
    return {player.id: Profile.model_validate(player) for player in rows}


async def reset_ratings(db: AsyncSession) -> None:
    await db.execute(
        update(Player).values(
            mmr=1200 + cast(func.trunc((Player.mmr - 1200) / 2), Integer)
        )
    )
