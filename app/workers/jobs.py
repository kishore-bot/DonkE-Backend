"""Background jobs on Taskiq.

Game-critical loops (matchmaking, turn deadlines, settlement) stay in the
custom Redis worker, where every step is fenced. Everything that may run a
little later lives here, as named tasks with retries and a schedule:

    taskiq worker app.workers.jobs:broker          # runs tasks
    taskiq scheduler app.workers.jobs:scheduler    # kicks scheduled tasks

Settlement only records a durable entry in Redis; the scheduled drain turns
those entries into `analyse_match` tasks, so a broker outage never blocks a
match from finishing.
"""

from typing import Annotated

from taskiq import (
    AsyncBroker,
    Context,
    InMemoryBroker,
    SimpleRetryMiddleware,
    TaskiqDepends,
    TaskiqEvents,
    TaskiqScheduler,
    TaskiqState,
)
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisStreamBroker

from app.core.config import Settings
from app.core.platform import Platform, open_platform
from app.modules.ai.services.fair_play import drain, run_analysis
from app.workers.maintenance import prune_sessions, sweep_media

settings = Settings()


def make_broker(config: Settings) -> AsyncBroker:
    if config.redis_dsn is None:
        return InMemoryBroker()  # Offline and unit tests: run tasks inline.
    prefix = config.redis_prefix
    return RedisStreamBroker(
        url=str(config.redis_dsn),
        queue_name=f"{prefix}:taskiq:jobs",
        consumer_group_name=f"{prefix}:taskiq:workers",
        maxlen=10_000,
    ).with_middlewares(SimpleRetryMiddleware(default_retry_count=3))


broker = make_broker(settings)
scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def open_stores(state: TaskiqState) -> None:
    state.platform_context = open_platform(settings)
    state.platform = await state.platform_context.__aenter__()


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def close_stores(state: TaskiqState) -> None:
    await state.platform_context.__aexit__(None, None, None)


def current_platform(context: Annotated[Context, TaskiqDepends()]) -> Platform:
    return context.state.platform


PLATFORM = TaskiqDepends(current_platform)


@broker.task(task_name="donke.analyse_match", retry_on_error=True, max_retries=3)
async def analyse_match(game_id: str, platform: Platform = PLATFORM) -> int:
    """Engine analysis and fair-play review of one settled ranked match."""
    return await run_analysis(platform, game_id)


@broker.task(task_name="donke.drain_analysis", schedule=[{"cron": "* * * * *"}])
async def drain_analysis(
    platform: Platform = PLATFORM,
) -> int:
    """Every minute: turn queued ranked matches into analysis tasks."""
    return await drain(platform, analyse_match.kiq)


@broker.task(task_name="donke.prune_sessions", schedule=[{"cron": "17 * * * *"}])
async def prune_expired_sessions(
    platform: Platform = PLATFORM,
) -> None:
    """Hourly: delete expired player and admin sessions."""
    await prune_sessions(platform)


@broker.task(task_name="donke.sweep_media", schedule=[{"cron": "43 * * * *"}])
async def sweep_orphaned_media(
    platform: Platform = PLATFORM,
) -> int:
    """Hourly: delete stored season objects that no media row references."""
    return await sweep_media(platform)
