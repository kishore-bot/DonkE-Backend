from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.identity.repository import profiles, reset_ratings
from app.modules.matches.repository import MatchRepository
from app.modules.matches.schemas import MatchAdmission, MatchRewards
from app.modules.progression.analytics import (
    MatchAnalytics,
    SeatStats,
    finishing_ranks,
)
from app.modules.progression.calendar import CLAIM_GRACE, claim_deadline, window_open
from app.modules.progression.catalog import (
    ACHIEVEMENTS,
    BONUS_TRACK,
    CATALOG,
    PERKS,
    SQUAD_COSMETIC,
    STREAK_DAYS,
    TIER_POINTS,
    TIERS,
    active_perks,
    bank_share,
    boosted_coins,
    in_window,
    tier_reached,
    window_end,
)
from app.modules.progression.models import (
    Achievement,
    CoinLedger,
    Cosmetic,
    PlayerSkill,
    PlayerStats,
    Season,
    SeasonCharacter,
    SeasonDay,
    SeasonPlayer,
    Wallet,
    WeeklyPlayer,
)
from app.modules.progression.schemas import (
    AchievementsView,
    AchievementView,
    BonusView,
    CatalogItem,
    ChallengeView,
    EarnedGift,
    MySeason,
    PerkView,
    SeasonCreate,
    SeasonGifts,
    SeasonInfo,
    Standing,
    TierView,
)
from app.modules.progression.skill import Rating, rate
from app.modules.progression.season_content import (
    PACKS,
    CharacterSelection,
    SeasonManifest,
)

CHALLENGES = {
    "play_three": ("Play three matches", "games", 3, 20),
    "play_seven": ("Play seven matches", "games", 7, 40),
    "escape_twice": ("Escape twice", "escapes", 2, 25),
    "give_three_cuts": ("Give three Strikes", "cuts", 3, 30),
    "give_eight_cuts": ("Give eight Strikes", "cuts", 8, 45),
}


def week_start(now: datetime, season: Season | None = None) -> date:
    day = now.astimezone(UTC).date()
    if season is not None and season.pack_key is not None:
        start = season.starts_at.astimezone(UTC).date()
        return day - timedelta(days=(day - start).days % 7)
    return day - timedelta(days=day.weekday())


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


async def active_season(db: AsyncSession, now: datetime) -> Season | None:
    return await db.scalar(
        select(Season)
        .where(
            Season.starts_at <= now, Season.ends_at > now, Season.closed_at.is_(None)
        )
        .order_by(Season.starts_at.desc())
        .limit(1)
        .with_for_update(read=True)
    )


async def lock_season_schedule(db: AsyncSession, *, read: bool = False) -> None:
    query = (
        "SELECT pg_advisory_xact_lock_shared(470053)"
        if read
        else "SELECT pg_advisory_xact_lock(470053)"
    )
    await db.execute(text(query))


async def match_admission(
    db: AsyncSession, now: datetime
) -> tuple[MatchAdmission, datetime | None]:
    candidate = await db.scalar(
        select(Season)
        .where(Season.ends_at > now, Season.closed_at.is_(None))
        .order_by(Season.starts_at)
        .limit(1)
    )
    if candidate is not None and candidate.starts_at <= now:
        return (
            MatchAdmission(
                season_id=candidate.id,
                season_title=candidate.theme,
                pack_key=candidate.pack_key,
            ),
            candidate.ends_at,
        )
    return MatchAdmission(season_id=None), candidate.starts_at if candidate else None


async def create_season(db: AsyncSession, request: SeasonCreate) -> SeasonInfo:
    await lock_season_schedule(db)
    overlapping = await db.scalar(
        select(Season.id)
        .where(
            Season.starts_at < request.ends_at,
            Season.ends_at > request.starts_at,
        )
        .limit(1)
    )
    if overlapping is not None:
        raise AppError(
            409, "season_overlap", "Choose a season window without an overlap"
        )
    pack = PACKS[request.pack_key] if request.pack_key is not None else None
    if pack is not None:
        packed = select(Season.pack_key).where(Season.pack_key.is_not(None))
        before = await db.scalar(
            packed.where(Season.ends_at <= request.starts_at)
            .order_by(Season.ends_at.desc())
            .limit(1)
        )
        after = await db.scalar(
            packed.where(Season.starts_at >= request.ends_at)
            .order_by(Season.starts_at)
            .limit(1)
        )
        if any(
            key in PACKS and PACKS[key].anime_id == pack.anime_id
            for key in (before, after)
            if key
        ):
            raise AppError(
                409,
                "season_anime_repeated",
                "Choose a different anime from adjacent seasons",
            )
    row = Season(
        theme=pack.title if pack is not None else request.theme,
        pack_key=request.pack_key,
        starts_at=request.starts_at,
        ends_at=request.ends_at,
    )
    db.add(row)
    await db.flush()
    return SeasonInfo.model_validate(row)


async def active_manifest(db: AsyncSession, now: datetime) -> SeasonManifest | None:
    season = await active_season(db, now)
    if season is None or season.pack_key is None:
        return None
    pack = PACKS.get(season.pack_key)
    if pack is None:
        raise AppError(503, "season_pack_unavailable", "Season content is unavailable")
    return SeasonManifest(
        season_id=season.id,
        pack_key=season.pack_key,
        starts_at=season.starts_at,
        ends_at=season.ends_at,
        pack=pack,
    )


async def season_character(
    db: AsyncSession,
    season_id: UUID,
    player_id: UUID,
    now: datetime,
    *,
    character_id: str | None = None,
) -> CharacterSelection:
    manifest = await active_manifest(db, now)
    if manifest is None or manifest.season_id != season_id:
        raise AppError(409, "season_unavailable", "This season is unavailable")
    if character_id is None:
        saved = await db.get(SeasonCharacter, (season_id, player_id))
        return CharacterSelection(character_id=saved.character_id if saved else None)
    if not any(character.id == character_id for character in manifest.pack.cast):
        raise AppError(
            404, "season_character_not_found", "Character is unavailable in this season"
        )
    row = insert(SeasonCharacter).values(
        season_id=season_id, player_id=player_id, character_id=character_id
    )
    await db.execute(
        row.on_conflict_do_update(
            index_elements=[SeasonCharacter.season_id, SeasonCharacter.player_id],
            set_={"character_id": row.excluded.character_id},
        )
    )
    return CharacterSelection(character_id=character_id)


async def own(db: AsyncSession, player: UUID, sku: str) -> None:
    await db.execute(
        insert(Cosmetic).values(player_id=player, sku=sku).on_conflict_do_nothing()
    )


async def close_season(
    db: AsyncSession, matches: MatchRepository, season_id: UUID, now: datetime
) -> SeasonInfo:
    await lock_season_schedule(db)
    season = await db.get(Season, season_id, with_for_update=True)
    if season is None:
        raise AppError(404, "season_not_found", "Season not found")
    if season.closed_at:
        return SeasonInfo.model_validate(season)
    if now < season.ends_at:
        raise AppError(409, "season_active", "The season has not ended")
    settlement_status = await matches.season_settlement_status(
        season.starts_at, season.ends_at, season_id=season.id
    )
    if settlement_status == "active":
        raise AppError(409, "season_active", "The season has not ended")
    if settlement_status == "pending":
        raise AppError(
            409,
            "season_settlement_pending",
            "Wait for the season's match results to settle",
        )
    rows = await db.scalars(
        select(SeasonPlayer)
        .where(SeasonPlayer.season_id == season.id)
        .order_by(SeasonPlayer.player_id)
    )
    for row in rows:
        wallet = await wallet_lock(db, row.player_id)
        prefix = f"season:{season.id}:{row.player_id}"
        if row.bank:
            await credit(db, wallet, prefix + ":bank", "bank", row.bank)
        reward = next(
            (
                coins
                for threshold, coins in [
                    (5000, 2500),
                    (4000, 1400),
                    (2800, 800),
                    (2200, 400),
                    (1000, 100),
                ]
                if row.peak_mmr >= threshold
            ),
            0,
        )
        if reward:
            await credit(db, wallet, prefix + ":peak", "peak", reward)
        if row.peak_mmr >= 2200:
            await own(db, row.player_id, f"season:{season.id}:title")
            await own(db, row.player_id, f"season:{season.id}:frame")
    # The soft reset belongs at the season boundary. If a later season is
    # already running, resetting now would rewrite ratings players earned in
    # it, so the rewards are paid but the reset is skipped.
    next_started = await db.scalar(
        select(Season.id)
        .where(
            Season.id != season.id,
            Season.starts_at >= season.ends_at,
            Season.starts_at <= now,
        )
        .limit(1)
    )
    if next_started is None:
        await reset_ratings(db)
    season.closed_at = now
    season.ratings_reset = next_started is None
    return SeasonInfo.model_validate(season)


TIER_REWARDS = {10: "card_back", 20: "title", 25: "emote", 30: "frame"}
EARNED_COSMETICS = {
    "tier": "Season tier",
    "bonus": "Streak bonus",
    "season": "Season reward",
}


def cosmetic_slot(sku: str) -> str:
    entry = CATALOG.get(sku)
    return entry.slot if entry else sku.rsplit(":", 1)[-1]


def earned_cosmetic(sku: str, item: Cosmetic) -> CatalogItem:
    origin = sku.split(":", 1)[0]
    slot = cosmetic_slot(sku)
    label = (
        SQUAD_COSMETIC
        if origin == "squad"
        else f"{EARNED_COSMETICS.get(origin, 'Earned')} {slot.replace('_', ' ')}"
    )
    return CatalogItem(
        sku=sku,
        label=label,
        slot=slot,
        price=0,
        owned=True,
        equipped=item.equipped,
        available=False,
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


def claim_week(season: Season, now: datetime, selected: date | None = None) -> date:
    latest = week_start(min(now, season.ends_at - timedelta(microseconds=1)), season)
    if selected is None or selected == latest:
        return latest
    first = season.starts_at.astimezone(UTC).date()
    if (
        season.pack_key is None
        or not first <= selected < latest
        or (selected - first).days % 7
    ):
        raise AppError(409, "reward_week_unavailable", "Choose an act from this season")
    return selected


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


async def update_skills(db: AsyncSession, analytics: MatchAnalytics) -> None:
    """Rate every human at the table against each other; bots are ignored."""
    humans = [
        (seat.seat, seat.player_id)
        for seat in analytics.seats
        # Players who left (now bot seats) are rated too, ranked last:
        # leaving must not protect a falling rating.
        if seat.player_id is not None
    ]
    if len(humans) < 2:
        return
    ids = sorted(player for _, player in humans)
    for player in ids:
        await db.execute(
            insert(PlayerSkill).values(player_id=player).on_conflict_do_nothing()
        )
    rows = {
        row.player_id: row
        for row in await db.scalars(
            select(PlayerSkill)
            .where(PlayerSkill.player_id.in_(ids))
            .order_by(PlayerSkill.player_id)
            .with_for_update()
        )
    }
    ranks = finishing_ranks(analytics)
    after = rate(
        [Rating(rows[player].mu, rows[player].sigma) for _, player in humans],
        [ranks[seat] for seat, _ in humans],
    )
    for (_, player), rating in zip(humans, after, strict=True):
        rows[player].mu = rating.mu
        rows[player].sigma = rating.sigma
        rows[player].matches += 1


async def hidden_skills(db: AsyncSession, players: list[UUID]) -> dict[UUID, Rating]:
    """Matchmaking skill per player; unrated players get the default."""
    rows = await db.scalars(
        select(PlayerSkill).where(PlayerSkill.player_id.in_(players))
    )
    found = {row.player_id: Rating(row.mu, row.sigma) for row in rows}
    return {player: found.get(player, Rating()) for player in players}


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


class ProgressionService:
    def __init__(self, platform: Platform):
        self.platform = platform

    async def balance(self, player: UUID) -> int:
        async with self.platform.sessions() as db:
            value = await db.get(Wallet, player)
            return value.coins if value else 0

    async def inventory(self, player: UUID) -> list[str]:
        async with self.platform.sessions() as db:
            return list(
                await db.scalars(
                    select(Cosmetic.sku)
                    .where(Cosmetic.player_id == player)
                    .order_by(Cosmetic.sku)
                )
            )

    async def catalog(self, player: UUID) -> list[CatalogItem]:
        async with self.platform.sessions() as db:
            owned = {
                item.sku: item
                for item in await db.scalars(
                    select(Cosmetic).where(Cosmetic.player_id == player)
                )
            }
        today = datetime.now(UTC).date()
        standard = [
            CatalogItem(
                sku=sku,
                label=item.label,
                slot=item.slot,
                price=item.price,
                owned=sku in owned,
                equipped=sku in owned and owned[sku].equipped,
                festival=item.festival,
                available=in_window(item.window, today),
                available_until=window_end(item.window, today),
            )
            for sku, item in CATALOG.items()
        ]
        return standard + [
            earned_cosmetic(sku, item)
            for sku, item in sorted(owned.items())
            if sku not in CATALOG
        ]

    async def buy(self, player: UUID, sku: str) -> int:
        product = CATALOG.get(sku)
        if product is None:
            raise AppError(404, "cosmetic_not_found", "Cosmetic not found")
        async with self.platform.sessions.begin() as db:
            wallet = await wallet_lock(db, player)
            if await db.get(Cosmetic, (player, sku)) is not None:
                return wallet.coins
            if not in_window(product.window, datetime.now(UTC).date()):
                raise AppError(
                    409,
                    "cosmetic_unavailable",
                    f"{product.label} returns for {product.festival}",
                )
            if wallet.coins < product.price:
                raise AppError(
                    409, "insufficient_coins", "Earn more coins to buy this cosmetic"
                )
            await credit(db, wallet, f"buy:{player}:{sku}", "purchase", -product.price)
            await own(db, player, sku)
            return wallet.coins

    async def equip(self, player: UUID, sku: str) -> None:
        async with self.platform.sessions.begin() as db:
            await wallet_lock(db, player)
            owned = list(
                await db.scalars(select(Cosmetic).where(Cosmetic.player_id == player))
            )
            selected = next((item for item in owned if item.sku == sku), None)
            if selected is None:
                raise AppError(
                    404, "cosmetic_not_owned", "Cosmetic not found in inventory"
                )

            slot = cosmetic_slot(sku)
            for item in owned:
                if cosmetic_slot(item.sku) == slot:
                    item.equipped = item.sku == sku

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
