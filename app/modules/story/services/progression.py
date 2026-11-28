from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.progression.helpers.calendar import (
    CLAIM_GRACE,
    claim_deadline,
    window_open,
)
from app.modules.progression.models.season import Season
from app.modules.progression.models.season_character import SeasonCharacter
from app.modules.progression.models.season_player import SeasonPlayer
from app.modules.progression.models.season_story_progress import SeasonStoryProgress
from app.modules.story.helpers.awakening import (
    AWAKENING_POINTS,
    requirements,
    resolve_path,
)
from app.modules.story.schemas.progression import (
    AwakeningPath,
    PendingAwakening,
    StoryProgress,
)


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
