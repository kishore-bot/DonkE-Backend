from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.repositories.players import profiles
from app.modules.matches.schemas.results import MatchRewards
from app.modules.progression.helpers.calendar import week_start
from app.modules.progression.helpers.catalog import (
    ACHIEVEMENTS,
    active_perks,
    bank_share,
    boosted_coins,
)
from app.modules.progression.models.achievement import Achievement
from app.modules.progression.models.coin_ledger import CoinLedger
from app.modules.progression.models.player_stats import PlayerStats
from app.modules.progression.models.season import Season
from app.modules.progression.models.season_day import SeasonDay
from app.modules.progression.models.season_player import SeasonPlayer
from app.modules.progression.models.wallet import Wallet
from app.modules.progression.models.weekly_player import WeeklyPlayer
from app.modules.progression.repositories.economy import credit, wallet_lock
from app.modules.progression.schemas.analytics import MatchAnalytics, SeatStats
from app.modules.progression.services.skill_updates import update_skills


async def record_stats(
    db: AsyncSession,
    wallet: Wallet,
    player: UUID,
    seat: SeatStats,
    now: datetime,
    *,
    decided: bool,
) -> None:
    """Update lifetime counters and pay out newly unlocked achievements.

    Only matches that reached a result (a Donkey or everyone safe) move the
    safe streak; time-limited or abandoned matches leave it unchanged."""
    await db.execute(
        insert(PlayerStats).values(player_id=player).on_conflict_do_nothing()
    )
    row = await db.get(PlayerStats, player, with_for_update=True)
    assert row is not None
    row.games += 1
    row.escapes += int(seat.place is not None)
    row.firsts += int(seat.place == 1)
    row.donkeys += int(seat.donkey)
    row.cuts_given += seat.cuts_given
    row.cards_picked += seat.cards_picked
    if decided:
        row.safe_streak = 0 if seat.donkey else row.safe_streak + 1
    row.best_safe_streak = max(row.best_safe_streak, row.safe_streak)
    for key, spec in ACHIEVEMENTS.items():
        if getattr(row, spec.stat) < spec.target:
            continue
        unlocked = await db.scalar(
            insert(Achievement)
            .values(player_id=player, key=key, unlocked_at=now)
            .on_conflict_do_nothing()
            .returning(Achievement.key)
        )
        if unlocked is not None:
            await credit(
                db,
                wallet,
                f"achievement:{key}:{player}",
                "achievement",
                spec.coins,
                earned_at=now,
            )


async def on_match(
    db: AsyncSession, analytics: MatchAnalytics, season: Season | None, now: datetime
) -> dict[UUID, MatchRewards]:
    eligible = sorted(
        (
            (seat.player_id, seat.seat)
            for seat in analytics.seats
            if seat.player_id is not None and not seat.bot and not seat.forfeited
        ),
    )
    # Match ratings already changed in this transaction.
    entrants = await profiles(db, [player for player, _ in eligible]) if season else {}
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_midnight = midnight + timedelta(days=1)
    decided = analytics.outcome.get("reason") in {"donkey", "all_safe"}
    season_time = (
        min(now, season.ends_at - timedelta(microseconds=1)) if season else now
    )
    rewards: dict[UUID, MatchRewards] = {}
    for player, index in eligible:
        wallet = await wallet_lock(db, player)
        seat = analytics.seats[index]
        escaped = int(seat.place is not None)
        cuts = seat.cuts_given
        progress = (
            await db.get(SeasonPlayer, (season.id, player), with_for_update=True)
            if season is not None and player in entrants
            else None
        )
        perks = active_perks(progress.points) if progress else set()
        awarded = await db.scalar(
            select(func.coalesce(func.sum(CoinLedger.amount), 0)).where(
                CoinLedger.player_id == player,
                CoinLedger.kind == "match",
                CoinLedger.created_at >= midnight,
                CoinLedger.created_at < next_midnight,
            )
        )
        amount = min(
            boosted_coins(10 + 5 * escaped, perks), max(0, 100 - (awarded or 0))
        )
        if amount and not await credit(
            db,
            wallet,
            f"match:{analytics.id}:{player}",
            "match",
            amount,
            earned_at=now,
        ):
            amount = 0
        award = rewards[player] = MatchRewards(coins=amount)
        await record_stats(db, wallet, player, seat, now, decided=decided)
        if season is None or player not in entrants:
            continue
        points = 5 + 3 * escaped + 2 * cuts
        bank = bank_share(amount, perks)
        award.season_points, award.bank_coins = points, bank
        row = insert(SeasonPlayer).values(
            season_id=season.id,
            player_id=player,
            points=points,
            bank=bank,
            peak_mmr=entrants[player].mmr,
        )
        await db.execute(
            row.on_conflict_do_update(
                index_elements=[SeasonPlayer.season_id, SeasonPlayer.player_id],
                set_={
                    "points": SeasonPlayer.points + points,
                    "bank": SeasonPlayer.bank + bank,
                    "peak_mmr": func.greatest(
                        SeasonPlayer.peak_mmr, entrants[player].mmr
                    ),
                },
            )
        )
        weekly = insert(WeeklyPlayer).values(
            season_id=season.id,
            player_id=player,
            week=week_start(season_time, season),
            games=1,
            escapes=escaped,
            cuts=cuts,
        )
        await db.execute(
            weekly.on_conflict_do_update(
                index_elements=[
                    WeeklyPlayer.season_id,
                    WeeklyPlayer.player_id,
                    WeeklyPlayer.week,
                ],
                set_={
                    "games": WeeklyPlayer.games + 1,
                    "escapes": WeeklyPlayer.escapes + escaped,
                    "cuts": WeeklyPlayer.cuts + cuts,
                },
            )
        )
        await db.execute(
            insert(SeasonDay)
            .values(season_id=season.id, player_id=player, day=season_time.date())
            .on_conflict_do_nothing()
        )
    await update_skills(db, analytics)
    return rewards
