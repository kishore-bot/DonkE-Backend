from datetime import UTC, datetime

from app.core.platform import Platform
from app.modules.admin.repository import prune_expired as prune_admin_sessions
from app.modules.game.story_store import prune_expired as prune_story_duels
from app.modules.identity.repository import prune_expired as prune_player_sessions


async def prune_sessions(platform: Platform) -> None:
    now = datetime.now(UTC)
    async with platform.sessions.begin() as db:
        await prune_player_sessions(db, now)
        await prune_admin_sessions(db, now)
        await prune_story_duels(db, now)
