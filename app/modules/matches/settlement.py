from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.ai import rivals
from app.modules.identity.repository import apply_rating
from app.modules.matches.models import MatchRecord
from app.modules.matches.schemas import MatchReplay
from app.modules.progression.service import active_season, on_match


def pending_analysis_key(platform: Platform) -> str:
    return f"{platform.settings.redis_prefix}:ai:analysis:pending"


def rated_changes(replay: MatchReplay) -> dict[UUID, int]:
    humans = [
        (index, seat) for index, seat in enumerate(replay.seats) if seat.player_id
    ]
    changes: dict[UUID, int] = {}
    if replay.mode != "ranked":
        return changes
    rank_stake = {1: 3, 2: 5, 3: 8, 4: 10}.get(len(humans), 10)
    loser = (
        replay.outcome.get("seat") if replay.outcome.get("reason") == "donkey" else None
    )
    for index, seat in humans:
        player_id = seat.player_id
        if player_id is None:
            continue
        if seat.forfeited:
            changes[player_id] = -(rank_stake + 2)
        elif loser == index:
            changes[player_id] = -rank_stake
        elif loser is not None and not seat.bot:
            changes[player_id] = min(3, rank_stake)
    return changes


async def persist(
    platform: Platform, replay: MatchReplay, *, finished_at: datetime | None = None
) -> bool:
    completed = (finished_at or datetime.now(UTC)).astimezone(UTC)
    async with platform.sessions.begin() as db:
        query = insert(MatchRecord).values(
            id=replay.id, replay=replay.model_dump(mode="json"), finished_at=completed
        )
        applied = await db.scalar(
            query.on_conflict_do_nothing().returning(MatchRecord.id)
        )
        if applied is None:
            return False
        await db.execute(text("SELECT pg_advisory_xact_lock_shared(470053)"))
        season = await active_season(db, completed)
        for player_id, delta in sorted(rated_changes(replay).items()):
            await apply_rating(db, player_id, delta)
        await on_match(db, replay, season, completed)
        await rivals.record(db, replay)
    if replay.mode == "ranked" and replay.opening is not None:
        # Fair-play review runs in the worker; settlement stays fast.
        await platform.redis.zadd(
            pending_analysis_key(platform), {str(replay.id): completed.timestamp()}
        )
    return True


async def load_replay(platform: Platform, game_id: UUID) -> MatchReplay | None:
    async with platform.sessions() as db:
        record = await db.get(MatchRecord, game_id)
    return MatchReplay.model_validate(record.replay) if record else None


async def read_replay(
    platform: Platform, game_id: UUID, player_id: UUID
) -> MatchReplay:
    async with platform.sessions() as db:
        record = await db.get(MatchRecord, game_id)
        if record is not None:
            replay = MatchReplay.model_validate(record.replay)
            if any(seat.player_id == player_id for seat in replay.seats):
                return replay
    raise AppError(404, "game_not_found", "Match replay not found")
