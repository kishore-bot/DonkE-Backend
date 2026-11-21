import asyncio
import contextlib
from dataclasses import dataclass
from uuid import UUID
import logging
import signal

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from sqlalchemy import select

from app.core.platform import Platform, open_platform
from app.modules.progression.service import hidden_skills
from app.modules.social.models import PlayerBlock
from app.modules.lobby.repository import LobbyConflict, LobbyRepository
from app.modules.lobby.service import QUEUES, LobbyService
from app.modules.matches.repository import MatchConflict
from app.modules.matches.service import MatchService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DatabaseFacts:
    """Hidden skill and blocks from Postgres for skill-aware tables."""

    platform: Platform

    async def load(
        self, players: list[UUID]
    ) -> tuple[dict[UUID, float], list[tuple[str, str]]]:
        async with self.platform.sessions() as db:
            skills = await hidden_skills(db, players)
            rows = await db.execute(
                select(PlayerBlock.blocker_id, PlayerBlock.blocked_id).where(
                    PlayerBlock.blocker_id.in_(players),
                    PlayerBlock.blocked_id.in_(players),
                )
            )
            blocks = [(str(a), str(b)) for a, b in rows.all()]
        return {player: rating.mu for player, rating in skills.items()}, blocks


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


async def run(platform: Platform, stop: asyncio.Event) -> None:
    """Game-critical loop only. Background jobs run on Taskiq (app.workers.jobs)."""
    lobby = LobbyService(
        LobbyRepository(platform.redis, platform.settings), DatabaseFacts(platform)
    )
    matches = MatchService(platform)
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
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                stop.wait(), timeout=platform.settings.matchmaking_poll_seconds
            )


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
