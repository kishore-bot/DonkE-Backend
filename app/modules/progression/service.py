from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.identity.repository import profiles, reset_ratings
from app.modules.matches.schemas import MatchReplay
from app.modules.progression.models import (
    CoinLedger,
    Cosmetic,
    Season,
    SeasonPlayer,
    Wallet,
    WeeklyPlayer,
)
from app.modules.progression.schemas import (
    CatalogItem,
    ChallengeView,
    MySeason,
    SeasonCreate,
    SeasonInfo,
    Standing,
    TierView,
)


@dataclass(frozen=True, slots=True)
class CatalogProduct:
    label: str
    slot: str
    price: int


CATALOG = {
    "monsoon_back": CatalogProduct("Monsoon card back", "card_back", 60),
    "poorayil_frame": CatalogProduct("Poorayil festival frame", "frame", 90),
    "kettuvallam_title": CatalogProduct("Kettuvallam Captain", "title", 75),
}
CHALLENGES = {
    "play_three": ("Play three matches", "games", 3, 20),
    "play_seven": ("Play seven matches", "games", 7, 40),
    "escape_twice": ("Escape twice", "escapes", 2, 25),
    "give_three_cuts": ("Give three Vettus", "cuts", 3, 30),
    "give_eight_cuts": ("Give eight Vettus", "cuts", 8, 45),
}


def week_start(now: datetime) -> date:
    day = now.astimezone(UTC).date()
    return day - timedelta(days=day.weekday())


async def wallet_lock(db: AsyncSession, player: UUID) -> Wallet:
    await db.execute(insert(Wallet).values(player_id=player).on_conflict_do_nothing())
    wallet = await db.get(Wallet, player, with_for_update=True)
    assert wallet is not None
    return wallet


async def credit(
    db: AsyncSession, wallet: Wallet, reference: str, kind: str, amount: int
) -> bool:
    query = (
        insert(CoinLedger)
        .values(
            reference=reference, player_id=wallet.player_id, kind=kind, amount=amount
        )
        .on_conflict_do_nothing()
        .returning(CoinLedger.reference)
    )
    if await db.scalar(query) is None:
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


async def create_season(db: AsyncSession, request: SeasonCreate) -> SeasonInfo:
    await db.execute(text("SELECT pg_advisory_xact_lock(470052)"))
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
    row = Season(
        theme=request.theme, starts_at=request.starts_at, ends_at=request.ends_at
    )
    db.add(row)
    await db.flush()
    return SeasonInfo.model_validate(row)


async def own(db: AsyncSession, player: UUID, sku: str) -> None:
    await db.execute(
        insert(Cosmetic).values(player_id=player, sku=sku).on_conflict_do_nothing()
    )


async def close_season(db: AsyncSession, season_id: UUID, now: datetime) -> SeasonInfo:
    await db.execute(text("SELECT pg_advisory_xact_lock(470053)"))
    season = await db.get(Season, season_id, with_for_update=True)
    if season is None:
        raise AppError(404, "season_not_found", "Season not found")
    if season.closed_at:
        return SeasonInfo.model_validate(season)
    if now < season.ends_at:
        raise AppError(409, "season_active", "The season has not ended")
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
    await reset_ratings(db)
    season.closed_at = now
    return SeasonInfo.model_validate(season)


async def on_match(
    db: AsyncSession, replay: MatchReplay, season: Season | None, now: datetime
) -> None:
    eligible = sorted(
        (
            (seat.player_id, index)
            for index, seat in enumerate(replay.seats)
            if seat.player_id is not None and not seat.bot and not seat.forfeited
        ),
    )
    # Match ratings already changed in this transaction.
    entrants = await profiles(db, [player for player, _ in eligible]) if season else {}
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    played = [event for batch in replay.events for event in batch.events]
    for player, index in eligible:
        wallet = await wallet_lock(db, player)
        escaped = int(
            any(
                event["event"] == "player_escaped" and event["seat"] == index
                for event in played
            )
        )
        cuts = sum(
            event["event"] == "vettu" and event["cutter"] == index for event in played
        )
        awarded = await db.scalar(
            select(func.coalesce(func.sum(CoinLedger.amount), 0)).where(
                CoinLedger.player_id == player,
                CoinLedger.kind == "match",
                CoinLedger.created_at >= midnight,
            )
        )
        amount = min(10 + 5 * escaped, max(0, 100 - (awarded or 0)))
        if amount:
            await credit(db, wallet, f"match:{replay.id}:{player}", "match", amount)
        if season is None or player not in entrants:
            continue
        points = 5 + 3 * escaped + 2 * cuts
        row = insert(SeasonPlayer).values(
            season_id=season.id,
            player_id=player,
            points=points,
            bank=amount // 5,
            peak_mmr=entrants[player].mmr,
        )
        await db.execute(
            row.on_conflict_do_update(
                index_elements=[SeasonPlayer.season_id, SeasonPlayer.player_id],
                set_={
                    "points": SeasonPlayer.points + points,
                    "bank": SeasonPlayer.bank + amount // 5,
                    "peak_mmr": func.greatest(
                        SeasonPlayer.peak_mmr, entrants[player].mmr
                    ),
                },
            )
        )
        weekly = insert(WeeklyPlayer).values(
            season_id=season.id,
            player_id=player,
            week=week_start(now),
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
        return [
            CatalogItem(
                sku=sku,
                label=item.label,
                slot=item.slot,
                price=item.price,
                owned=sku in owned,
                equipped=sku in owned and owned[sku].equipped,
            )
            for sku, item in CATALOG.items()
        ]

    async def buy(self, player: UUID, sku: str) -> int:
        product = CATALOG.get(sku)
        if product is None:
            raise AppError(404, "cosmetic_not_found", "Cosmetic not found")
        async with self.platform.sessions.begin() as db:
            wallet = await wallet_lock(db, player)
            if await db.get(Cosmetic, (player, sku)) is not None:
                return wallet.coins
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

            def slot(key: str) -> str:
                return CATALOG[key].slot if key in CATALOG else key.rsplit(":", 1)[-1]

            for item in owned:
                if slot(item.sku) == slot(sku):
                    item.equipped = item.sku == sku

    async def current(self, player: UUID) -> MySeason | None:
        now = datetime.now(UTC)
        async with self.platform.sessions() as db:
            season = await active_season(db, now)
            if season is None:
                return None
            progress = await db.get(SeasonPlayer, (season.id, player))
            week = week_start(now)
            weekly = await db.get(WeeklyPlayer, (season.id, player, week))
            refs = set(
                await db.scalars(
                    select(CoinLedger.reference).where(
                        CoinLedger.player_id == player,
                        CoinLedger.kind.in_(["tier", "challenge"]),
                    )
                )
            )
            return MySeason(
                season=SeasonInfo.model_validate(season),
                points=progress.points if progress else 0,
                bank=progress.bank if progress else 0,
                peak_mmr=progress.peak_mmr if progress else 0,
                tiers=[
                    TierView(
                        tier=i,
                        points=10 * i,
                        coins=5 + i,
                        claimed=f"tier:{season.id}:{player}:{i}" in refs,
                    )
                    for i in range(1, 31)
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

    async def claim(
        self,
        player: UUID,
        season_id: UUID,
        *,
        tier: int | None = None,
        challenge: str | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        async with self.platform.sessions.begin() as db:
            season = await active_season(db, now)
            if season is None or season.id != season_id:
                raise AppError(409, "season_unavailable", "This season is unavailable")
            wallet = await wallet_lock(db, player)
            progress = await db.get(SeasonPlayer, (season.id, player))
            if tier is not None:
                if progress is None or progress.points < 10 * tier:
                    raise AppError(409, "tier_locked", "Earn more season points")
                credited = await credit(
                    db, wallet, f"tier:{season_id}:{player}:{tier}", "tier", 5 + tier
                )
                if credited and tier in {10, 20, 30}:
                    slot = {10: "card_back", 20: "title", 30: "frame"}[tier]
                    await own(db, player, f"tier:{season_id}:{tier}:{slot}")
                return credited
            if challenge not in CHALLENGES:
                raise AppError(404, "challenge_not_found", "Challenge not found")
            _, attribute, target, points = CHALLENGES[challenge]
            week = week_start(now)
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
