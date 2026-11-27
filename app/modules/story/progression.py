from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.game.schemas import StoryObjective
from app.modules.game.story_state import StoryPin
from app.modules.progression import squad
from app.modules.progression.calendar import CLAIM_GRACE, claim_deadline, window_open
from app.modules.progression.models import (
    Season,
    SeasonChapterClear,
    SeasonCharacter,
    SeasonPlayer,
    SeasonStoryProgress,
)
from app.modules.progression.repositories.economy import credit, wallet_lock
from app.modules.progression.services.seasons import lock_season_schedule
from app.modules.story.awakening import (
    AWAKENING_POINTS,
    PATH_VERSION,
    PathStep,
    Requirement,
    requirements,
    resolve_path,
)
from app.modules.story.chapters import OPENING_CHAPTER, chapter_for


class StoryProgress(BaseModel):
    cleared: bool
    points: int
    target: int = AWAKENING_POINTS
    awakened_character_id: str | None
    missing: list[Requirement]


class StoryResult(BaseModel):
    escaped: bool
    first_clear: bool
    coins: int
    points: int
    objective: StoryObjective | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class AwakeningPath(StoryProgress):
    version: str = PATH_VERSION
    character_id: str | None
    claim_deadline: datetime
    claim_available: bool
    steps: list[PathStep]


class PendingAwakening(BaseModel):
    season_id: UUID
    title: str


def project(
    story: SeasonStoryProgress | None, points: int, character: str | None
) -> StoryProgress:
    awakened = story.awakened_character_id if story else None
    return StoryProgress(
        cleared=story is not None,
        points=points,
        awakened_character_id=awakened,
        missing=[]
        if awakened
        else requirements(character is not None, story is not None, points),
    )


def progress_rows(player_id: UUID):
    return (
        select(
            Season,
            SeasonStoryProgress,
            SeasonPlayer.points,
            SeasonCharacter.character_id,
        )
        .select_from(Season)
        .outerjoin(
            SeasonStoryProgress,
            and_(
                SeasonStoryProgress.season_id == Season.id,
                SeasonStoryProgress.player_id == player_id,
            ),
        )
        .outerjoin(
            SeasonPlayer,
            and_(
                SeasonPlayer.season_id == Season.id,
                SeasonPlayer.player_id == player_id,
            ),
        )
        .outerjoin(
            SeasonCharacter,
            and_(
                SeasonCharacter.season_id == Season.id,
                SeasonCharacter.player_id == player_id,
            ),
        )
    )


async def read_progress(
    db: AsyncSession, season_id: UUID, player_id: UUID
) -> tuple[Season | None, StoryProgress, str | None]:
    query = progress_rows(player_id).where(Season.id == season_id)
    row = (await db.execute(query)).one_or_none()
    if row is None:
        return None, project(None, 0, None), None
    season, story, points, character = row
    return season, project(story, points or 0, character), character


async def pending_awakening(
    db: AsyncSession, player_id: UUID, now: datetime
) -> PendingAwakening | None:
    query = (
        progress_rows(player_id)
        .where(
            Season.pack_key.is_not(None),
            Season.ends_at <= now,
            Season.ends_at > now - CLAIM_GRACE,
            SeasonStoryProgress.player_id.is_not(None),
            SeasonStoryProgress.awakened_character_id.is_(None),
            SeasonPlayer.points >= AWAKENING_POINTS,
            SeasonCharacter.character_id.is_not(None),
        )
        .order_by(Season.ends_at.desc())
        .limit(1)
    )
    row = (await db.execute(query)).one_or_none()
    return PendingAwakening(season_id=row[0].id, title=row[0].theme) if row else None


async def progress(db: AsyncSession, season_id: UUID, player_id: UUID) -> StoryProgress:
    _, state, _ = await read_progress(db, season_id, player_id)
    return state


async def awakening_path(
    db: AsyncSession, season_id: UUID, player_id: UUID, now: datetime
) -> AwakeningPath:
    season, state, character = await read_progress(db, season_id, player_id)
    if season is None or season.pack_key is None:
        raise AppError(404, "season_not_found", "Season not found")
    steps = resolve_path(
        state.missing,
        season.closed_at is None and season.starts_at <= now < season.ends_at,
        window_open(season.starts_at, season.ends_at, now),
        bool(state.awakened_character_id),
    )
    return AwakeningPath(
        **state.model_dump(),
        character_id=state.awakened_character_id or character,
        claim_deadline=claim_deadline(season.ends_at),
        claim_available=any(
            step.id == "claim_form" and step.status == "ready" for step in steps
        ),
        steps=steps,
    )


async def settle(
    db: AsyncSession,
    pin: StoryPin,
    player_id: UUID,
    game_id: UUID,
    escaped: bool,
    now: datetime,
    objective: StoryObjective | None = None,
) -> StoryResult:
    chapter = chapter_for(pin.pack_key, pin.chapter_id)
    first_clear = False
    if escaped and (objective is None or objective.met):
        await lock_season_schedule(db, read=True)
        wallet = await wallet_lock(db, player_id)
        season = await db.get(Season, pin.season_id)
        if season is None or season.pack_key != pin.pack_key:
            raise AppError(409, "season_unavailable", "This season is unavailable")
        row_key = (pin.season_id, player_id)
        suffix = "" if chapter.id == OPENING_CHAPTER else f":{chapter.id}"
        if chapter.id == OPENING_CHAPTER:
            inserted = await db.scalar(
                insert(SeasonStoryProgress)
                .values(
                    season_id=pin.season_id, player_id=player_id, clear_game_id=game_id
                )
                .on_conflict_do_nothing()
                .returning(SeasonStoryProgress.clear_game_id)
            )
            stored = (
                await db.get(SeasonStoryProgress, row_key) if inserted is None else None
            )
            first_clear = inserted is not None or (
                stored is not None and stored.clear_game_id == game_id
            )
        else:
            inserted = await db.scalar(
                insert(SeasonChapterClear)
                .values(
                    season_id=pin.season_id,
                    player_id=player_id,
                    chapter_id=chapter.id,
                    game_id=game_id,
                )
                .on_conflict_do_nothing()
                .returning(SeasonChapterClear.game_id)
            )
            old = (
                await db.get(SeasonChapterClear, (*row_key, chapter.id))
                if inserted is None
                else None
            )
            first_clear = inserted is not None or (
                old is not None and old.game_id == game_id
            )
        if inserted is not None:
            points = insert(SeasonPlayer).values(
                season_id=pin.season_id, player_id=player_id, points=chapter.points
            )
            await db.execute(
                points.on_conflict_do_update(
                    index_elements=[SeasonPlayer.season_id, SeasonPlayer.player_id],
                    set_={"points": SeasonPlayer.points + chapter.points},
                )
            )
            await credit(
                db,
                wallet,
                f"story:{pin.season_id}:{player_id}{suffix}",
                "story",
                chapter.coins,
            )
        if pin.squad_party_id is not None:
            await squad.contribute(
                db, season, pin.squad_party_id, player_id, game_id, now
            )
    return StoryResult(
        escaped=escaped,
        first_clear=first_clear,
        coins=chapter.coins if first_clear else 0,
        points=chapter.points if first_clear else 0,
        objective=objective,
    )


async def awaken(
    db: AsyncSession,
    season_id: UUID,
    player_id: UUID,
    now: datetime,
) -> StoryProgress:
    season = await db.get(Season, season_id)
    if season is None or season.pack_key is None:
        raise AppError(404, "season_not_found", "Season not found")
    await wallet_lock(db, player_id)
    story = await db.get(
        SeasonStoryProgress, (season_id, player_id), with_for_update=True
    )
    if story is not None and story.awakened_character_id is not None:
        return await progress(db, season_id, player_id)
    if not window_open(season.starts_at, season.ends_at, now):
        raise AppError(
            409, "claim_window_closed", "The awakening claim window has closed"
        )
    player = await db.get(SeasonPlayer, (season_id, player_id))
    selection = await db.get(
        SeasonCharacter, (season_id, player_id), with_for_update=True
    )
    if requirements(
        selection is not None, story is not None, player.points if player else 0
    ):
        raise AppError(
            409,
            "awakening_locked",
            "Choose a character, clear the duel and earn 300 season points",
        )
    assert story is not None
    assert selection is not None
    story.awakened_character_id = selection.character_id
    await db.flush()
    return await progress(db, season_id, player_id)
