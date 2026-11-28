"""One durable public moment per player, season and rival."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.game.dto.story_pin import StoryPin
from app.modules.game.models.story_rival_memory import StoryRivalMemory
from app.modules.game.schemas.story import StoryEvent


async def remember(
    db: AsyncSession, pin: StoryPin, now: datetime, events: tuple[StoryEvent, ...]
) -> None:
    moment = next((event for event in reversed(events) if event.kind == "strike"), None)
    if moment is None:
        moment = next(
            (event for event in reversed(events) if event.kind == "escaped"), None
        )
    if moment is None:
        return
    row = insert(StoryRivalMemory).values(
        season_id=pin.season_id,
        player_id=pin.player_id,
        chapter_id=pin.chapter_id,
        finished_at=now,
        moment=moment.model_dump(exclude_none=True),
    )
    await db.execute(
        row.on_conflict_do_update(
            index_elements=[
                StoryRivalMemory.season_id,
                StoryRivalMemory.player_id,
                StoryRivalMemory.chapter_id,
            ],
            set_={
                "finished_at": row.excluded.finished_at,
                "moment": row.excluded.moment,
            },
            where=StoryRivalMemory.finished_at < row.excluded.finished_at,
        )
    )


async def recall(
    db: AsyncSession, season: UUID, player: UUID, chapter: str
) -> StoryEvent | None:
    row = await db.get(StoryRivalMemory, (season, player, chapter))
    return StoryEvent.model_validate(row.moment) if row else None
