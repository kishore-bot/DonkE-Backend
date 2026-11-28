"""Player-scoped collection and replays of previously cleared chapters."""

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.game.dto.story_pin import StoryPin
from app.modules.progression.helpers.season_content import PACKS
from app.modules.progression.models.season import Season
from app.modules.progression.models.season_chapter_clear import SeasonChapterClear
from app.modules.progression.models.season_character import SeasonCharacter
from app.modules.progression.models.season_story_progress import SeasonStoryProgress
from app.modules.progression.schemas.content import CharacterPreview
from app.modules.story.dto.chapter import Chapter
from app.modules.story.helpers.chapters import CHAPTERS, OPENING_CHAPTER, chapter_for
from app.modules.story.schemas.archive import ArchiveChapter, CollectionEntry
from app.modules.story.services.chapters import cleared_chapters
from app.modules.story.services.progression import progress_rows


async def collection(
    db: AsyncSession, player: UUID, now: datetime
) -> list[CollectionEntry]:
    query = (
        progress_rows(player)
        .where(
            Season.pack_key.is_not(None),
            (Season.ends_at <= now) | Season.closed_at.is_not(None),
        )
        .where(
            SeasonCharacter.player_id.is_not(None)
            | SeasonStoryProgress.player_id.is_not(None)
        )
        .order_by(Season.ends_at.desc(), Season.id)
    )
    rows = (await db.execute(query)).all()
    clears = defaultdict(set)
    for season_id, chapter_id in await db.execute(
        select(SeasonChapterClear.season_id, SeasonChapterClear.chapter_id).where(
            SeasonChapterClear.player_id == player,
            SeasonChapterClear.season_id.in_([season.id for season, *_ in rows]),
        )
    ):
        clears[season_id].add(chapter_id)
    entries = []
    for season, story, _, selected in rows:
        pack_key = season.pack_key
        pack = PACKS.get(pack_key or "")
        if pack is None or pack_key is None:
            continue
        awakened = story.awakened_character_id if story else None
        character_id = awakened or selected
        character = next(
            (item for item in pack.cast if item.id == character_id), pack.cast[0]
        )
        cleared = clears[season.id]
        if story is not None:
            cleared.add(OPENING_CHAPTER)
        entries.append(
            CollectionEntry(
                season_id=season.id,
                title=season.theme,
                ended_at=season.ends_at,
                pack_key=pack_key,
                character=character,
                awakened=awakened is not None,
                chapters=[
                    ArchiveChapter(id=chapter.id, title=chapter.title)
                    for chapter in CHAPTERS.get(pack_key, ())
                    if chapter.id in cleared
                ],
            )
        )
    return entries


async def archive_attempt(
    db: AsyncSession, player: UUID, season_id: UUID, chapter_id: str, now: datetime
) -> tuple[StoryPin, CharacterPreview, Chapter]:
    row = (
        await db.execute(
            progress_rows(player).where(
                Season.id == season_id,
                (Season.ends_at <= now) | Season.closed_at.is_not(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise AppError(404, "archive_not_found", "This archived chapter is unavailable")
    season, story, _, selected = row
    if season.pack_key not in PACKS or chapter_id not in await cleared_chapters(
        db, season_id, player
    ):
        raise AppError(404, "archive_not_found", "This archived chapter is unavailable")
    pack = PACKS[season.pack_key]
    awakened = story.awakened_character_id if story else None
    character = next(
        (item for item in pack.cast if item.id == (awakened or selected)), pack.cast[0]
    )
    return (
        StoryPin(
            season_id,
            season.pack_key,
            character.id,
            None,
            chapter_id=chapter_id,
            route=next(iter(pack.routes), None),
        ),
        character,
        chapter_for(season.pack_key, chapter_id),
    )
