from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progression.catalog import (
    STREAK_DAYS,
)
from app.modules.progression.models import (
    CoinLedger,
    Cosmetic,
    Season,
    SeasonDay,
    Wallet,
)


async def wallet_lock(db: AsyncSession, player: UUID) -> Wallet:
    await db.execute(insert(Wallet).values(player_id=player).on_conflict_do_nothing())
    wallet = await db.get(Wallet, player, with_for_update=True)
    assert wallet is not None
    return wallet


async def credit(
    db: AsyncSession,
    wallet: Wallet,
    reference: str,
    kind: str,
    amount: int,
    *,
    earned_at: datetime | None = None,
) -> bool:
    query = insert(CoinLedger).values(
        reference=reference, player_id=wallet.player_id, kind=kind, amount=amount
    )
    if earned_at is not None:
        query = query.values(created_at=earned_at)
    if (
        await db.scalar(query.on_conflict_do_nothing().returning(CoinLedger.reference))
        is None
    ):
        return False
    wallet.coins += amount
    return True


async def own(db: AsyncSession, player: UUID, sku: str) -> None:
    await db.execute(
        insert(Cosmetic).values(player_id=player, sku=sku).on_conflict_do_nothing()
    )


async def reward_refs(db: AsyncSession, season_id: UUID, player: UUID) -> set[str]:
    return set(
        await db.scalars(
            select(CoinLedger.reference).where(
                CoinLedger.player_id == player,
                or_(
                    CoinLedger.reference.startswith(f"tier:{season_id}:{player}:"),
                    CoinLedger.reference.startswith(f"week:{season_id}:{player}:"),
                    CoinLedger.reference.startswith(f"bonus:{season_id}:{player}:"),
                ),
            )
        )
    )


async def streak_stars(db: AsyncSession, season_id: UUID, player: UUID) -> int:
    """Weeks in the season with at least STREAK_DAYS distinct play days."""
    season = await db.get(Season, season_id)
    week = func.date_trunc("week", SeasonDay.day)
    if season is not None and season.pack_key is not None:
        start = season.starts_at.astimezone(UTC).date()
        week = func.floor((SeasonDay.day - start) / 7)
    weeks = (
        select(week)
        .where(SeasonDay.season_id == season_id, SeasonDay.player_id == player)
        .group_by(week)
        .having(func.count() >= STREAK_DAYS)
        .subquery()
    )
    return await db.scalar(select(func.count()).select_from(weeks)) or 0
