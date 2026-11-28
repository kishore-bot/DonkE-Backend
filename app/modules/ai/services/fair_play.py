"""Fair-play review. Ranked matches are analysed in the background; the Rust
engine turns a player's recent decisions into signals and a score. A score at
or above QUEUE_SCORE opens a case for a moderator. Nothing is sanctioned
automatically."""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from donke_engine import fair_play_stats
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.ai.models.fair_play_case import FairPlayCase
from app.modules.ai.models.match_analysis import MatchAnalysis
from app.modules.ai.repositories.fair_play_queue import (
    QUEUE_SCORE,
    claim_pending,
    pending_key,
)
from app.modules.ai.schemas.coaching import Sample
from app.modules.ai.schemas.fair_play import CaseView, Resolve
from app.modules.ai.services.coaching import stored_analysis
from app.modules.matches.repositories.history import load_replay

logger = logging.getLogger(__name__)


WINDOW_DAYS = 30


async def review(db: AsyncSession, player: UUID, now: datetime) -> CaseView | None:
    """Score the player's recent analysed decisions; open or refresh a case."""
    rows = await db.scalars(
        select(MatchAnalysis.payload).where(
            MatchAnalysis.player_id == player,
            MatchAnalysis.created_at >= now - timedelta(days=WINDOW_DAYS),
        )
    )
    decisions = [
        {
            "think_ms": sample.think_ms,
            "legal_moves": sample.legal,
            "matched_engine_top": sample.top,
        }
        for payload in rows
        for sample in (
            Sample.model_validate(item) for item in payload.get("samples", [])
        )
        if sample.think_ms is not None
    ]
    stats = json.loads(fair_play_stats(json.dumps(decisions)))
    if stats["score"] < QUEUE_SCORE:
        return None
    case = await db.scalar(
        select(FairPlayCase)
        .where(FairPlayCase.player_id == player, FairPlayCase.status == "open")
        .with_for_update()
    )
    if case is None:
        case = FairPlayCase(player_id=player, score=stats["score"], stats=stats)
        db.add(case)
    else:
        case.score, case.stats = stats["score"], stats
    await db.flush()
    await db.refresh(case)
    return CaseView.model_validate(case)


async def analyse_ranked(platform: Platform, game_id: UUID) -> int:
    """Analyse every human seat of a settled ranked match, then review them."""
    replay = await load_replay(platform, game_id)
    if replay is None:
        return 0
    humans = [
        # Includes players a bot replaced: their own earlier moves still count.
        # The bot's moves are flagged `auto` and skipped by the analysis.
        seat.player_id
        for seat in replay.seats
        if seat.player_id
    ]
    opened = 0
    for player in humans:
        await stored_analysis(platform, replay, player)
        async with platform.sessions.begin() as db:
            opened += int(await review(db, player, datetime.now(UTC)) is not None)
    return opened


async def run_analysis(platform: Platform, game: str) -> int:
    """Analyse one claimed match. Store errors raise, so the job retries;
    a replay that can never be analysed is dropped."""
    try:
        opened = await analyse_ranked(platform, UUID(game))
    except AppError as error:
        logger.info("Skipping analysis of %s (%s)", game, error.code)
        opened = 0
    await platform.redis.zrem(pending_key(platform), game)
    return opened


async def drain(
    platform: Platform, send: Callable[[str], Awaitable[object]], limit: int = 20
) -> int:
    """Hand each claimed match to `send` (a Taskiq kick in production)."""
    claimed = await claim_pending(platform, limit)
    for game in claimed:
        await send(game)
    return len(claimed)


async def cases(platform: Platform, status: str) -> list[CaseView]:
    async with platform.sessions() as db:
        rows = await db.scalars(
            select(FairPlayCase)
            .where(FairPlayCase.status == status)
            .order_by(FairPlayCase.score.desc(), FairPlayCase.created_at)
            .limit(100)
        )
        return [CaseView.model_validate(row) for row in rows]


async def resolve(db: AsyncSession, case_id: UUID, body: Resolve) -> CaseView:
    case = await db.get(FairPlayCase, case_id, with_for_update=True)
    if case is None:
        raise AppError(404, "case_not_found", "Fair-play case not found")
    if case.status == "open":
        case.status = body.decision
        case.note = body.reason
        case.resolved_at = datetime.now(UTC)
    await db.flush()
    return CaseView.model_validate(case)
