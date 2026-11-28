from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.platform import Platform
from app.modules.admin.repository import prune_expired as prune_admin_sessions
from app.modules.game.repositories.story import prune_expired as prune_story_duels
from app.modules.identity.repository import prune_expired as prune_player_sessions
from app.modules.story.media import ObjectStorage
from app.modules.story.models import SeasonMedia


async def prune_sessions(platform: Platform) -> None:
    now = datetime.now(UTC)
    async with platform.sessions.begin() as db:
        await prune_player_sessions(db, now)
        await prune_admin_sessions(db, now)
        await prune_story_duels(db, now)


ORPHAN_AGE = timedelta(hours=1)


async def sweep_media(platform: Platform) -> int:
    """Delete stored season objects that no media row references.

    An upload stores the object before its row commits, so a crash in between
    leaves an orphan. Objects younger than an hour are skipped so an upload in
    progress is never removed. Returns how many objects were deleted; keys
    that fail stay for the next run."""
    if not platform.settings.season_media_bucket:
        return 0
    storage = ObjectStorage(platform.settings)
    keys = await run_in_threadpool(
        storage.keys_before, "seasons/", datetime.now(UTC) - ORPHAN_AGE
    )
    orphans = []
    async with platform.sessions() as db:
        for start in range(0, len(keys), 500):
            batch = keys[start : start + 500]
            known = set(
                await db.scalars(
                    select(SeasonMedia.object_key).where(
                        SeasonMedia.object_key.in_(batch)
                    )
                )
            )
            orphans.extend(key for key in batch if key not in known)
    if not orphans:
        return 0
    failed = await run_in_threadpool(storage.delete_many, orphans)
    return len(orphans) - len(failed)
