from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.identity.repository import reset_ratings
from app.modules.matches.repository import MatchRepository
from app.modules.matches.schemas import MatchAdmission
from app.modules.progression.models import (
    Season,
    SeasonCharacter,
    SeasonPlayer,
)
from app.modules.progression.repositories.economy import credit, own, wallet_lock
from app.modules.progression.schemas import (
    SeasonCreate,
    SeasonInfo,
)
from app.modules.progression.season_content import (
    PACKS,
    CharacterSelection,
    SeasonManifest,
)


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
