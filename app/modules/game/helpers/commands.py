"""The same move and retry rules for local practice and stored story duels."""

import json

from donke_engine import PracticeGame

from app.core.errors import AppError
from app.modules.game.helpers.seeded_duel import SeededDuel
from app.modules.game.schemas.practice import (
    MoveScore,
    PracticeHint,
    PracticePlayRequest,
)
from app.modules.game.schemas.views import GameUpdate


def validate_retry(previous: PracticePlayRequest, command: PracticePlayRequest) -> None:
    if previous != command:
        raise AppError(
            409, "request_id_reused", "Request ID belongs to a different play"
        )


def play_game(
    game: PracticeGame | SeededDuel, command: PracticePlayRequest
) -> tuple[PracticeGame | SeededDuel, GameUpdate]:
    if command.expected_version != game.version:
        raise AppError(409, "stale_version", "Get the latest view before playing")
    if command.call_strike and not isinstance(game, SeededDuel):
        raise AppError(
            409, "strike_call_unavailable", "Strike calls are available in story duels"
        )
    try:
        card = command.card.model_dump_json()
        if isinstance(game, SeededDuel):
            next_game, result = game.play(card, command.call_strike)
        else:
            next_game, result = game.play(card)
    except ValueError as exc:
        code = str(exc)
        errors = {
            "strike_call_unavailable": (
                409,
                "You can call once before leading a story trick",
            ),
            "game_finished": (409, "This match has finished"),
            "illegal_card": (422, "This card cannot be played now"),
        }
        if code in errors:
            status, message = errors[code]
            raise AppError(status, code, message) from exc
        raise
    return next_game, GameUpdate.model_validate_json(result)


def hint_game(game: PracticeGame | SeededDuel, iterations: int) -> PracticeHint:
    options = [
        MoveScore.model_validate(score) for score in json.loads(game.hint(iterations))
    ]
    return PracticeHint(best=options[0].card if options else None, options=options)
