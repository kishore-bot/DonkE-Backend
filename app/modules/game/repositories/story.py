from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Integer, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.game.models.story_duel import StoryDuel
from app.modules.game.models.story_duel_command import StoryDuelCommand
from app.modules.identity.models.player import Player


async def prune_expired(db: AsyncSession, now: datetime) -> None:
    await db.execute(delete(StoryDuel).where(StoryDuel.expires_at <= now))


async def lock_player(db: AsyncSession, player: UUID) -> bool:
    identity = await db.scalar(
        select(Player.id).where(Player.id == player).with_for_update()
    )
    return identity is not None


async def count_active(db: AsyncSession, player: UUID, now: datetime) -> int:
    count = await db.scalar(
        select(func.count(StoryDuel.id)).where(
            StoryDuel.player_id == player,
            StoryDuel.expires_at > now,
            StoryDuel.finished.is_(False),
        )
    )
    return count or 0


async def latest_attempt(
    db: AsyncSession, player: UUID, now: datetime
) -> StoryDuel | None:
    return await db.scalar(
        select(StoryDuel)
        .where(
            StoryDuel.player_id == player,
            StoryDuel.expires_at > now,
            StoryDuel.receipt.is_(None),
        )
        .order_by(StoryDuel.created_at.desc(), StoryDuel.id)
        .limit(1)
    )


async def legacy_updates(db: AsyncSession, game_id: UUID) -> Sequence[dict]:
    return (
        await db.scalars(
            select(StoryDuelCommand.update)
            .where(StoryDuelCommand.duel_id == game_id)
            .order_by(StoryDuelCommand.command["expected_version"].astext.cast(Integer))
        )
    ).all()
