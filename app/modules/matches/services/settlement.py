from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.ai.services import rivals
from app.modules.identity.repositories.players import apply_rating
from app.modules.matches.helpers.keys import pending_analysis_key
from app.modules.matches.helpers.ratings import rated_changes
from app.modules.matches.models.match_player import MatchPlayer
from app.modules.matches.models.match_record import MatchRecord
from app.modules.matches.schemas.results import MatchReplay, MatchRewards
from app.modules.matches.services.results import participant_receipt
from app.modules.progression.models.season import Season
from app.modules.progression.services.analytics import match_analytics
from app.modules.progression.services.match_rewards import on_match
from app.modules.progression.services.seasons import active_season, lock_season_schedule


async def persist(
    platform: Platform, replay: MatchReplay, *, finished_at: datetime | None = None
) -> bool:
    """Store a finished match once. Returns False if it was already stored.

    Queueing fair-play analysis happens after the commit on every attempt,
    including retries: if an earlier attempt committed but died before
    queueing, the retry repairs it. The queue is a sorted set, so queueing
    twice is harmless."""
    completed = (finished_at or datetime.now(UTC)).astimezone(UTC)
    async with platform.sessions.begin() as db:
        applied = await record(db, replay, completed)
    if replay.mode == "ranked" and replay.opening is not None:
        await platform.redis.zadd(
            pending_analysis_key(platform),
            {str(replay.id): completed.timestamp()},
            nx=True,
        )
    return applied


async def record(db: AsyncSession, replay: MatchReplay, completed: datetime) -> bool:
    """Every durable effect of a finished match, in one transaction."""
    query = insert(MatchRecord).values(
        id=replay.id, replay=replay.model_dump(mode="json"), finished_at=completed
    )
    if (
        await db.scalar(query.on_conflict_do_nothing().returning(MatchRecord.id))
        is None
    ):
        return False
    await lock_season_schedule(db, read=True)
    if replay.admission is None:
        season = await active_season(db, completed)
    elif replay.admission.season_id is None:
        season = None
    else:
        season = await db.get(Season, replay.admission.season_id)
        if season is None or season.closed_at is not None:
            raise AppError(
                409, "admitted_season_unavailable", "Match season is unavailable"
            )
    changes = {
        player_id: await apply_rating(db, player_id, delta)
        for player_id, delta in sorted(rated_changes(replay).items())
    }
    analytics = match_analytics(replay)
    rewards = await on_match(db, analytics, season, completed)
    seated = []
    for seat in analytics.seats:
        if seat.player_id is None:
            continue
        award = rewards.get(seat.player_id, MatchRewards())
        award.mmr_delta = changes.get(seat.player_id, 0)
        receipt = participant_receipt(
            replay, seat, completed, season.id if season else None, award
        )
        seated.append(
            {
                "game_id": replay.id,
                "player_id": seat.player_id,
                "seat": seat.seat,
                "finished_at": completed,
                "receipt": receipt.model_dump(mode="json"),
            }
        )
    if seated:
        await db.execute(insert(MatchPlayer).values(seated))
    await rivals.record(db, replay)
    return True
