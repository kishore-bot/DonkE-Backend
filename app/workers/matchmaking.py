import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.platform import Platform, open_platform
from app.modules.lobby.repository import LobbyConflict, LobbyRepository
from app.modules.lobby.service import QUEUES, LobbyService
from app.modules.matches.health import record_turn_sweep
from app.modules.matches.repository import MatchConflict
from app.modules.matches.service import TURN_CONCURRENCY, MatchService
from app.modules.progression.services.skill_updates import hidden_skills
from app.modules.social.models import PlayerBlock

logger = logging.getLogger(__name__)
RETRYABLE = (RedisError, SQLAlchemyError, OSError, LobbyConflict, MatchConflict)


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


async def poll(
    name: str, work: Callable[[], Awaitable[object]], stop: asyncio.Event, delay: float
) -> None:
    while not stop.is_set():
        try:
            await work()
        except RETRYABLE as error:
            logger.warning("%s poll failed (%s)", name, type(error).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)


async def run_turns(matches: MatchService, stop: asyncio.Event, delay: float) -> None:
    active: set[UUID] = set()

    async def advance(game_id: UUID) -> None:
        try:
            await matches.on_deadline(game_id)
        except RETRYABLE as error:
            logger.warning(
                "Turn poll failed for %s (%s)", game_id, type(error).__name__
            )
        finally:
            active.remove(game_id)

    async with asyncio.TaskGroup() as tasks:

        async def sweep() -> None:
            for game_id in await matches.repo.due("turns"):
                if len(active) >= TURN_CONCURRENCY:
                    break
                if game_id not in active:
                    active.add(game_id)
                    tasks.create_task(advance(game_id))
            await record_turn_sweep(matches.platform, await matches.repo.now_ms())

        await poll("Turn scheduler", sweep, stop, delay)


async def run(platform: Platform, stop: asyncio.Event) -> None:
    """Schedule game work independently of Taskiq background jobs."""
    lobby = LobbyService(
        LobbyRepository(platform.redis, platform.settings), DatabaseFacts(platform)
    )
    matches = MatchService(platform)
    delay = platform.settings.matchmaking_poll_seconds
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(poll("Matchmaking", lambda: match_once(lobby), stop, delay))
        tasks.create_task(poll("Room start", matches.start_ready_rooms, stop, delay))
        tasks.create_task(poll("Settlement", matches.settle_finished, stop, delay))
        tasks.create_task(run_turns(matches, stop, delay))


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
