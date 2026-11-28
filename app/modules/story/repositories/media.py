from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.story.models.season_media import SeasonMedia


async def approved_media(
    db: AsyncSession, pack: str, character: str, slot: str
) -> SeasonMedia | None:
    return await db.scalar(
        select(SeasonMedia)
        .where(
            SeasonMedia.pack_key == pack,
            SeasonMedia.character_id == character,
            SeasonMedia.slot == slot,
            SeasonMedia.published_at.is_not(None),
            SeasonMedia.withdrawn_at.is_(None),
        )
        .order_by(SeasonMedia.published_at.desc(), SeasonMedia.id.desc())
        .limit(1)
    )
