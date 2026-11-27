import json
from collections import deque
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

    def _admit(self, client: str, now: float) -> None:
        """Caps checked before any bot runs, so rejected requests cost nothing.
        Must hold the repository lock."""
        sessions = self.repository.sessions
        for game_id in [key for key, s in sessions.items() if s.expires_at <= now]:
            del sessions[game_id]
        created = self.repository.created
        while created:
            oldest = next(iter(created.values()))
            if oldest[-1] > now - 60:
                break
            created.popitem(last=False)
        recent = created.get(client, deque())
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= self.settings.practice_creates_per_minute:
            raise AppError(
                429, "rate_limited", "Too many practice matches. Wait a minute"
            )
        creating = self.repository.creating
        mine = sum(1 for session in sessions.values() if session.client == client)
        if mine + creating[client] >= self.settings.practice_sessions_per_client:
            raise AppError(
                429, "practice_limit", "Finish one of your practice matches first"
            )
        if len(sessions) + creating.total() >= self.settings.practice_max_sessions:
            raise AppError(503, "practice_full", "Practice is at capacity")
        recent.append(now)
        created[client] = recent
        created.move_to_end(client)
        creating[client] += 1

    def create(
        self,
        seats: int,
        level: Literal["easy", "medium", "hard"] = "medium",
        client: str = "unknown",
    ) -> PracticeCreated:
        with self.repository.lock:
            self._admit(client, monotonic())
        try:
            # Bots may play before the human's first turn: outside the table lock.
            game = PracticeGame(seats, level, iterations=200)
            update = GameUpdate.model_validate_json(game.snapshot())
            game_id, token = uuid4(), token_urlsafe(32)
            session = PracticeSession(
                game=game,
                token_digest=sha256(token.encode()).digest(),
                expires_at=monotonic() + self.settings.practice_session_ttl_seconds,
                client=client,
            )
            response = PracticeCreated(
                game_id=game_id,
                access_token=token,
                view=update.view,
                events=update.events,
            )
        except BaseException:
            with self.repository.lock:
                self._release(client)
            raise
        with self.repository.lock:
            self.repository.sessions[game_id] = session
            self._release(client)
        return response

    def _release(self, client: str) -> None:
        creating = self.repository.creating
        creating[client] -= 1
        if creating[client] == 0:
            del creating[client]

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
        with session.lock:
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
