from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.progression.calendar import (
    week_start,
)
from app.modules.progression.catalog import (
    ACHIEVEMENTS,
    BONUS_TRACK,
    CHALLENGES,
    PERKS,
    STREAK_DAYS,
    TIER_POINTS,
    TIER_REWARDS,
    TIERS,
    active_perks,
)
from app.modules.progression.models import (
    Achievement,
    PlayerStats,
    Season,
    SeasonDay,
    SeasonPlayer,
    WeeklyPlayer,
)
from app.modules.progression.repositories.economy import (
    reward_refs,
    streak_stars,
)
from app.modules.progression.schemas import (
    AchievementsView,
    AchievementView,
    BonusView,
    ChallengeView,
    MySeason,
    PerkView,
    SeasonInfo,
    Standing,
    TierView,
)
from app.modules.progression.services.seasons import active_season


class SeasonProgressService:
    def __init__(self, platform: Platform):
        self.platform = platform

    async def current(self, player: UUID) -> MySeason | None:
        now = datetime.now(UTC)
        async with self.platform.sessions() as db:
            season = await active_season(db, now)
            if season is None:
                return None
            progress = await db.get(SeasonPlayer, (season.id, player))
            week = week_start(now, season)
            weekly = await db.get(WeeklyPlayer, (season.id, player, week))
            refs = await reward_refs(db, season.id, player)
            points = progress.points if progress else 0
            perks = active_perks(points)
            days = await db.scalar(
                select(func.count()).where(
                    SeasonDay.season_id == season.id,
                    SeasonDay.player_id == player,
                    SeasonDay.day >= week,
                    SeasonDay.day < week + timedelta(days=7),
                )
            )
            stars = await streak_stars(db, season.id, player)
            return MySeason(
                season=SeasonInfo.model_validate(season),
                points=points,
                bank=progress.bank if progress else 0,
                peak_mmr=progress.peak_mmr if progress else 0,
                tiers=[
                    TierView(
                        tier=i,
                        points=TIER_POINTS * i,
                        coins=5 + i,
                        reward=TIER_REWARDS.get(i),
                        claimed=f"tier:{season.id}:{player}:{i}" in refs,
                    )
                    for i in range(1, TIERS + 1)
                ],
                perks=[
                    PerkView(
                        key=perk.key,
                        title=perk.title,
                        tier=perk.tier,
                        active=perk.key in perks,
                    )
                    for perk in PERKS
                ],
                streak_days=days or 0,
                streak_target=STREAK_DAYS,
                stars=stars,
                bonus=[
                    BonusView(
                        tier=tier,
                        stars=needed,
                        reward=slot,
                        claimed=f"bonus:{season.id}:{player}:{tier}" in refs,
                    )
                    for tier, (needed, slot) in BONUS_TRACK.items()
                    if season.pack_key is None or needed <= 3
                ],
                weekly=[
                    ChallengeView(
                        key=key,
                        title=title,
                        progress=getattr(weekly, attribute, 0),
                        target=target,
                        points=points,
                        claimed=f"week:{season.id}:{player}:{week}:{key}" in refs,
                    )
                    for key, (title, attribute, target, points) in CHALLENGES.items()
                ],
            )

    async def board(self, season_id: UUID) -> list[Standing]:
        async with self.platform.sessions() as db:
            if await db.get(Season, season_id) is None:
                raise AppError(404, "season_not_found", "Season not found")
            rows = await db.scalars(
                select(SeasonPlayer)
                .where(SeasonPlayer.season_id == season_id)
                .order_by(
                    SeasonPlayer.peak_mmr.desc(),
                    SeasonPlayer.points.desc(),
                    SeasonPlayer.player_id,
                )
                .limit(100)
            )
            return [
                Standing(
                    player_id=row.player_id, points=row.points, peak_mmr=row.peak_mmr
                )
                for row in rows
            ]

    async def achievements(self, player: UUID) -> AchievementsView:
        async with self.platform.sessions() as db:
            stats = await db.get(PlayerStats, player)
            unlocked = {
                row.key: row.unlocked_at
                for row in await db.scalars(
                    select(Achievement).where(Achievement.player_id == player)
                )
            }
        counters = {
            name: (getattr(stats, name) if stats else 0)
            for name in (
                "games",
                "escapes",
                "firsts",
                "donkeys",
                "cuts_given",
                "cards_picked",
                "safe_streak",
                "best_safe_streak",
            )
        }
        return AchievementsView(
            stats=counters,
            achievements=[
                AchievementView(
                    key=key,
                    title=spec.title,
                    description=spec.description,
                    progress=min(counters[spec.stat], spec.target),
                    target=spec.target,
                    coins=spec.coins,
                    unlocked_at=unlocked.get(key),
                )
                for key, spec in ACHIEVEMENTS.items()
            ],
        )
