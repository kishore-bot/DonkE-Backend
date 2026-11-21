import json
from hashlib import sha256
from secrets import compare_digest, token_urlsafe
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

from donke_engine import PracticeGame

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.game.repository import (
    PracticeRepository,
    PracticeSession,
    RecordedPlay,
)
from app.modules.game.schemas import (
    GameUpdate,
    MoveScore,
    PlayRequest,
    PracticeCreated,
    PracticeHint,
)


class PracticeService:
    def __init__(self, repository: PracticeRepository, settings: Settings):
        self.repository = repository
        self.settings = settings

    def create(
        self, seats: int, level: Literal["easy", "medium", "hard"] = "medium"
    ) -> PracticeCreated:
        with self.repository.lock:
            now = monotonic()
            sessions = self.repository.sessions
            for game_id in [
                key for key, session in sessions.items() if session.expires_at <= now
            ]:
                del sessions[game_id]
            if len(sessions) >= self.settings.practice_max_sessions:
                raise AppError(503, "practice_full", "Practice is at capacity")

            game = PracticeGame(seats, level, iterations=200)
            update = GameUpdate.model_validate_json(game.snapshot())
            game_id, token = uuid4(), token_urlsafe(32)
            sessions[game_id] = PracticeSession(
                game=game,
                token_digest=sha256(token.encode()).digest(),
                expires_at=now + self.settings.practice_session_ttl_seconds,
            )
            return PracticeCreated(
                game_id=game_id,
                access_token=token,
                view=update.view,
                events=update.events,
            )

    def _session(self, game_id: UUID, token: str) -> PracticeSession:
        session = self.repository.sessions.get(game_id)
        if (
            session is None
            or session.expires_at <= monotonic()
            or not compare_digest(session.token_digest, sha256(token.encode()).digest())
        ):
            raise AppError(404, "practice_not_found", "Practice match not found")
        return session

    def hint(self, game_id: UUID, token: str) -> PracticeHint:
        with self.repository.lock:
            game = self._session(game_id, token).game
        options = [
            MoveScore.model_validate(score)
            for score in json.loads(game.hint(self.settings.practice_hint_iterations))
        ]
        return PracticeHint(best=options[0].card if options else None, options=options)

    def snapshot(self, game_id: UUID, token: str) -> GameUpdate:
        with self.repository.lock:
            return GameUpdate.model_validate_json(
                self._session(game_id, token).game.snapshot()
            )

    def play(self, game_id: UUID, token: str, command: PlayRequest) -> GameUpdate:
        with self.repository.lock:
            session = self._session(game_id, token)
            previous = session.plays.get(command.request_id)
            if previous is not None:
                if (previous.version, previous.card) != (
                    command.expected_version,
                    command.card,
                ):
                    raise AppError(
                        409,
                        "request_id_reused",
                        "Request ID belongs to a different play",
                    )
                return previous.outcome
            if command.expected_version != session.game.version:
                raise AppError(
                    409, "stale_version", "Get the latest view before playing"
                )
            try:
                next_game, result = session.game.play(command.card.model_dump_json())
            except ValueError as exc:
                code = str(exc)
                if code == "game_finished":
                    raise AppError(409, code, "This match has finished") from exc
                if code == "illegal_card":
                    raise AppError(422, code, "This card cannot be played now") from exc
                raise

            update = GameUpdate.model_validate_json(result)
            session.plays[command.request_id] = RecordedPlay(
                command.expected_version, command.card, update
            )
            session.game = next_game
            return update
