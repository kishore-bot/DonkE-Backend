from uuid import UUID

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.matches.schemas import (
    MatchState,
)


def unavailable() -> AppError:
    return AppError(404, "game_not_found", "Match not found")


def position(state: MatchState, player_id: UUID) -> int:
    for index, seat in enumerate(state.seats):
        if seat.player_id == player_id:
            return index
    raise unavailable()


def deadline(config: Settings, state: MatchState, now: int) -> int:
    if state.turn is None:
        return now
    delay = (
        config.bot_turn_seconds if state.seats[state.turn].bot else config.turn_seconds
    )
    return min(state.limit_ms, now + max(1, round(delay * 1000)))
