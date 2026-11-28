from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.story.models.season_cue import SeasonCue
from app.modules.story.schemas.lines import Moment


def cue_query(pack_key: str, character_id: str, moment: str):
    return select(SeasonCue).where(
        SeasonCue.pack_key == pack_key,
        SeasonCue.character_id == character_id,
        SeasonCue.moment == moment,
    )


async def published(
    db: AsyncSession, pack_key: str, character_id: str, moment: Moment
) -> tuple[str, str]:
    cue = await db.scalar(
        cue_query(pack_key, character_id, moment).where(SeasonCue.stage == "published")
    )
    if cue is None or cue.en is None or cue.ja is None:
        raise AppError(404, "cue_not_found", "Scene cue not found")
    return cue.en, cue.ja
