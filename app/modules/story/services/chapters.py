"""Versioned encounter definitions and the story admission rules."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progression.models.season_chapter_clear import SeasonChapterClear
from app.modules.progression.models.season_story_progress import SeasonStoryProgress
from app.modules.progression.schemas.content import SeasonManifest
from app.modules.story.dto.chapter import Chapter
from app.modules.story.helpers.chapters import OPENING_CHAPTER
from app.modules.story.schemas.chapters import ChapterView


async def cleared_chapters(
    db: AsyncSession, season: UUID, player: UUID | None
) -> set[str]:
    if player is None:
        return set()
    cleared = set(
        await db.scalars(
            select(SeasonChapterClear.chapter_id).where(
                SeasonChapterClear.season_id == season,
                SeasonChapterClear.player_id == player,
            )
        )
    )
    if await db.get(SeasonStoryProgress, (season, player)) is not None:
        cleared.add(OPENING_CHAPTER)
    return cleared


def describe(
    manifest: SeasonManifest,
    chapter: Chapter,
    player: UUID | None,
    cleared: set[str],
    now: datetime,
) -> ChapterView:
    opens = manifest.starts_at.astimezone(UTC) + timedelta(days=(chapter.act - 1) * 7)
    status: Literal["ready", "cleared", "scheduled", "sign_in", "prerequisite"] = (
        "ready"
    )
    if chapter.id in cleared:
        status = "cleared"
    elif now < opens:
        status = "scheduled"
    elif chapter.requires is not None:
        if player is None:
            status = "sign_in"
        elif chapter.requires not in cleared:
            status = "prerequisite"
    return ChapterView(
        chapter_id=chapter.id,
        act=chapter.act,
        title=chapter.title,
        rival=chapter.rival,
        opens_at=opens,
        requires=chapter.requires,
        coins=chapter.coins,
        points=chapter.points,
        status=status,
    )
