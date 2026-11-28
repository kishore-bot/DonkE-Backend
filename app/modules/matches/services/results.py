from datetime import datetime
from uuid import UUID

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.matches.models.match_player import MatchPlayer
from app.modules.matches.models.match_record import MatchRecord
from app.modules.matches.repositories.matches import MatchRepository
from app.modules.matches.schemas.results import (
    MatchReplay,
    MatchResult,
    MatchRewards,
    SettledResult,
    UnsettledResult,
)
from app.modules.progression.schemas.analytics import SeatStats
from app.modules.progression.services.analytics import match_analytics


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
