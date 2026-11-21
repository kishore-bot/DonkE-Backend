import asyncio
import logging
import signal
from datetime import UTC, datetime

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.platform import Platform, open_platform
from app.modules.admin.repository import prune_expired as prune_admin_sessions
from app.modules.ai.fair_play import analysis_tick
from app.modules.identity.repository import prune_expired as prune_player_sessions
from app.modules.lobby.repository import LobbyConflict, LobbyRepository
from app.modules.lobby.service import QUEUES, LobbyService
from app.modules.matches.repository import MatchConflict
from app.modules.matches.service import MatchService

logger = logging.getLogger(__name__)


async def match_once(lobby: LobbyService) -> int:
    await lobby.recover()
    created = 0
    for mode, queue in QUEUES:
        for _ in range(8):
            claim = await lobby.claim(mode, queue)
            if claim is None:
                break
            try:
                room = await lobby.finalize(claim)
            except RedisError, LobbyConflict:
                # Rollback is fenced. If the finalize actually committed, the claim is already gone.
                await lobby.rollback(claim)
                raise
            if room is not None:
                created += 1
    return created


async def prune_sessions(platform: Platform) -> None:
    now = datetime.now(UTC)
    async with platform.sessions.begin() as db:
        await prune_player_sessions(db, now)
        await prune_admin_sessions(db, now)


async def run(platform: Platform, stop: asyncio.Event) -> None:
    lobby = LobbyService(LobbyRepository(platform.redis, platform.settings))
    matches = MatchService(platform)
    next_prune = 0.0
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        try:
            await match_once(lobby)
            await matches.tick()
        except (
            RedisError,
            SQLAlchemyError,
            OSError,
            LobbyConflict,
            MatchConflict,
        ) as error:
            logger.warning("Matchmaking tick failed (%s)", type(error).__name__)
        try:
            await analysis_tick(platform)
        except (RedisError, SQLAlchemyError, OSError, AppError) as error:
            logger.warning("Analysis tick failed (%s)", type(error).__name__)
        if loop.time() >= next_prune:
            try:
                await prune_sessions(platform)
            except (SQLAlchemyError, OSError) as error:
                logger.warning("Session cleanup failed (%s)", type(error).__name__)
                next_prune = loop.time() + 60
            else:
                next_prune = loop.time() + 3600
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=platform.settings.matchmaking_poll_seconds
            )
        except TimeoutError:
            pass


async def main() -> None:
    stop = asyncio.Event()
    if hasattr(signal, "SIGTERM"):
        loop = asyncio.get_running_loop()
        for name in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(name, stop.set)
            except NotImplementedError:
                break
    async with open_platform(Settings()) as platform:
        await run(platform, stop)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
