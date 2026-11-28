from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.progression.helpers.calendar import (
    CLAIM_GRACE,
    claim_deadline,
    claim_week,
    window_open,
)
from app.modules.progression.helpers.catalog import (
    BONUS_TRACK,
    CHALLENGES,
    STREAK_DAYS,
    TIER_POINTS,
    TIER_REWARDS,
    tier_reached,
)
from app.modules.progression.models.season import Season
from app.modules.progression.models.season_player import SeasonPlayer
from app.modules.progression.models.weekly_player import WeeklyPlayer
from app.modules.progression.repositories.economy import (
    credit,
    own,
    reward_refs,
    streak_stars,
    wallet_lock,
)
from app.modules.progression.schemas.gifts import EarnedGift, SeasonGifts
from app.modules.progression.services.seasons import lock_season_schedule


class SeasonRewardsService:
    def __init__(self, platform: Platform):
        self.platform = platform

    async def gifts(self, player: UUID) -> list[SeasonGifts]:
        now = datetime.now(UTC)
        async with self.platform.sessions() as db:
            rows = await db.execute(
                select(Season, SeasonPlayer.points)
                .join(SeasonPlayer, SeasonPlayer.season_id == Season.id)
                .where(
                    SeasonPlayer.player_id == player,
                    Season.pack_key.is_not(None),
                    Season.starts_at <= now,
                    Season.ends_at > now - CLAIM_GRACE,
                )
                .order_by(Season.ends_at)
            )
            inbox = []
            for season, points in rows:
                refs = await reward_refs(db, season.id, player)
                first = season.starts_at.astimezone(UTC).date()
                weeks = await db.scalars(
                    select(WeeklyPlayer)
                    .where(
                        WeeklyPlayer.season_id == season.id,
                        WeeklyPlayer.player_id == player,
                        WeeklyPlayer.week >= first,
                        WeeklyPlayer.week <= claim_week(season, now),
                    )
                    .order_by(WeeklyPlayer.week)
                )
                stars = await streak_stars(db, season.id, player)
                gifts = [
                    EarnedGift(
                        kind="weekly",
                        key=key,
                        title=title,
                        week=entry.week,
                        act=(entry.week - first).days // 7 + 1,
                        points=award,
                        claimed=f"week:{season.id}:{player}:{entry.week}:{key}" in refs,
                    )
                    for entry in weeks
                    for key, (title, attribute, target, award) in CHALLENGES.items()
                    if getattr(entry, attribute) >= target
                ]
                gifts.extend(
                    EarnedGift(
                        kind="tiers",
                        key=str(tier),
                        title=f"Tier {tier}",
                        coins=5 + tier,
                        cosmetic=TIER_REWARDS.get(tier),
                        claimed=f"tier:{season.id}:{player}:{tier}" in refs,
                    )
                    for tier in range(1, tier_reached(points) + 1)
                )
                gifts.extend(
                    EarnedGift(
                        kind="bonus",
                        key=str(tier),
                        title=f"Streak bonus {tier}",
                        cosmetic=slot,
                        claimed=f"bonus:{season.id}:{player}:{tier}" in refs,
                    )
                    for tier, (needed, slot) in BONUS_TRACK.items()
                    if needed <= min(stars, 3)
                )
                if gifts:
                    inbox.append(
                        SeasonGifts(
                            season_id=season.id,
                            title=season.theme,
                            claim_deadline=claim_deadline(season.ends_at),
                            gifts=gifts,
                        )
                    )
            return inbox

    async def claim(
        self,
        player: UUID,
        season_id: UUID,
        *,
        tier: int | None = None,
        challenge: str | None = None,
        bonus: int | None = None,
        week: date | None = None,
    ) -> bool:
        async with self.platform.sessions.begin() as db:
            await lock_season_schedule(db, read=True)
            now = datetime.now(UTC)
            season = await db.get(Season, season_id)
            if season is None or not window_open(season.starts_at, season.ends_at, now):
                raise AppError(409, "season_unavailable", "This season is unavailable")
            if season.pack_key is None and (season.closed_at or now >= season.ends_at):
                raise AppError(409, "season_unavailable", "This season is unavailable")
            wallet = await wallet_lock(db, player)
            progress = await db.get(SeasonPlayer, (season.id, player))
            if tier is not None:
                if progress is None or progress.points < TIER_POINTS * tier:
                    raise AppError(409, "tier_locked", "Earn more season points")
                credited = await credit(
                    db, wallet, f"tier:{season_id}:{player}:{tier}", "tier", 5 + tier
                )
                if credited and tier in TIER_REWARDS:
                    slot = TIER_REWARDS[tier]
                    await own(db, player, f"tier:{season_id}:{tier}:{slot}")
                return credited
            if bonus is not None:
                if bonus not in BONUS_TRACK or (
                    season.pack_key is not None and BONUS_TRACK[bonus][0] > 3
                ):
                    raise AppError(404, "bonus_not_found", "Bonus tier not found")
                needed, slot = BONUS_TRACK[bonus]
                if await streak_stars(db, season.id, player) < needed:
                    raise AppError(
                        409,
                        "bonus_locked",
                        f"Play {STREAK_DAYS} days in a week to earn streak stars",
                    )
                credited = await credit(
                    db, wallet, f"bonus:{season_id}:{player}:{bonus}", "bonus", 0
                )
                if credited:
                    await own(db, player, f"bonus:{season_id}:{bonus}:{slot}")
                return credited
            if challenge not in CHALLENGES:
                raise AppError(404, "challenge_not_found", "Challenge not found")
            _, attribute, target, points = CHALLENGES[challenge]
            week = claim_week(season, now, week)
            weekly = await db.get(WeeklyPlayer, (season.id, player, week))
            if progress is None or getattr(weekly, attribute, 0) < target:
                raise AppError(
                    409, "challenge_locked", "Complete more of the weekly challenge"
                )
            credited = await credit(
                db,
                wallet,
                f"week:{season_id}:{player}:{week}:{challenge}",
                "challenge",
                0,
            )
            if credited:
                progress.points += points
            return credited
