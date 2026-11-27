"""Versioned encounter definitions and the story admission rules."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.progression.models import SeasonChapterClear, SeasonStoryProgress
from app.modules.progression.season_content import SeasonManifest

OPENING_CHAPTER = "trial"


@dataclass(frozen=True, slots=True)
class Chapter:
    id: str
    act: int
    title: str
    rival: str
    seed: int
    coins: int
    points: int
    requires: str | None = None


CHAPTERS = {
    "grimoire-awakening-v1": (
        Chapter(OPENING_CHAPTER, 1, "Arena Trial", "The Arena Keeper", 5, 20, 40),
        Chapter(
            "rival",
            2,
            "Grimoire Rivalry",
            "The Rune Tactician",
            13,
            20,
            35,
            OPENING_CHAPTER,
        ),
        Chapter(
            "finale", 3, "Awakening Trial", "The Hollow Warden", 37, 30, 55, "rival"
        ),
    ),
    "skybound-voyage-v1": (
        Chapter(OPENING_CHAPTER, 1, "Deck Trial", "The Storm Captain", 41, 20, 40),
        Chapter(
            "rival",
            2,
            "Crosswind Duel",
            "The Tide Navigator",
            61,
            20,
            35,
            OPENING_CHAPTER,
        ),
        Chapter(
            "finale", 3, "Eye of the Storm", "The Gale Warden", 83, 30, 55, "rival"
        ),
    ),
}


class ChapterView(BaseModel):
    chapter_id: str
    act: int
    title: str
    rival: str
    opens_at: datetime
    requires: str | None
    coins: int
    points: int
    status: Literal["ready", "cleared", "scheduled", "sign_in", "prerequisite"]


def chapter_for(pack: str, chapter_id: str = OPENING_CHAPTER) -> Chapter:
    chapter = next(
        (entry for entry in CHAPTERS.get(pack, ()) if entry.id == chapter_id), None
    )
    if chapter is None:
        raise AppError(404, "chapter_not_found", "This story chapter is unavailable")
    return chapter


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
