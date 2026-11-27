from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.ai import rivals
from app.modules.identity.repository import apply_rating
from app.modules.matches.models import MatchPlayer, MatchRecord
from app.modules.matches.repository import MatchRepository
from app.modules.matches.schemas import (
    MatchReplay,
    MatchResult,
    MatchRewards,
    RecentMatch,
    SettledResult,
    UnsettledResult,
)
from app.modules.progression.analytics import SeatStats, match_analytics
from app.modules.progression.models import Season
from app.modules.progression.service import (
    active_season,
    lock_season_schedule,
    on_match,
)


def pending_analysis_key(platform: Platform) -> str:
    return f"{platform.settings.redis_prefix}:ai:analysis:pending"


def rated_changes(replay: MatchReplay) -> dict[UUID, int]:
    humans = [
        (index, seat) for index, seat in enumerate(replay.seats) if seat.player_id
    ]
    changes: dict[UUID, int] = {}
    # Ratings measure play against people. A ranked table that bots filled
    # around a single human is unrated, so solo bot games cannot farm MMR
    # (and, through peak MMR, season rewards).
    if replay.mode != "ranked" or len(humans) < 2:
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


def participant_receipt(
    replay: MatchReplay,
    seat: SeatStats,
    completed: datetime,
    season_id: UUID | None = None,
    rewards: MatchRewards | None = None,
) -> SettledResult:
    result = SettledResult(
        admission=replay.admission,
        rewarded_season_id=season_id,
        finished_at=completed,
        outcome=str(replay.outcome.get("reason") or "finished"),
        placement="holding",
        rewards=rewards,
    )
    if seat.forfeited:
        result.placement = "forfeited"
    elif seat.donkey:
        result.placement = "donkey"
    elif seat.place is not None:
        result.placement, result.place = "escaped", seat.place
    return result


async def read_result(
    platform: Platform, game_id: UUID, player_id: UUID
) -> MatchResult:
    async with platform.sessions() as db:
        participant = await db.get(MatchPlayer, (game_id, player_id))
        if participant is not None:
            if participant.receipt is not None:
                return SettledResult.model_validate(participant.receipt)
            record = await db.get(MatchRecord, game_id)
            if record is not None:
                replay = MatchReplay.model_validate(record.replay)
                seat = match_analytics(replay).seats[participant.seat]
                return participant_receipt(replay, seat, participant.finished_at)
    state = await MatchRepository(platform).get(game_id)
    if state is None or not any(seat.player_id == player_id for seat in state.seats):
        raise AppError(404, "game_not_found", "Match result not found")
    return UnsettledResult(
        status="pending" if state.status == "finished" else "in_progress",
        admission=state.admission,
    )


async def recent_results(platform: Platform, player_id: UUID) -> list[RecentMatch]:
    async with platform.sessions() as db:
        rows = await db.execute(
            select(MatchPlayer.game_id, MatchPlayer.finished_at)
            .where(MatchPlayer.player_id == player_id)
            .order_by(MatchPlayer.finished_at.desc(), MatchPlayer.game_id)
            .limit(10)
        )
        return [
            RecentMatch(game_id=game_id, finished_at=finished_at)
            for game_id, finished_at in rows
        ]


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
