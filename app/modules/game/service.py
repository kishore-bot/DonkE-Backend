from collections import deque
from hashlib import sha256
from secrets import compare_digest, token_urlsafe
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

from donke_engine import OnlineGame, PracticeGame

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.game.commands import hint_game, play_game, validate_retry
from app.modules.game.repository import (
    PracticeRepository,
    PracticeSession,
    RecordedPlay,
    StoryPin,
)
from app.modules.game.seeded import SeededDuel
from app.modules.game.schemas import (
    GameUpdate,
    PracticeCreated,
    PracticeHint,
    PracticePlayRequest,
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
        mine = sum(
            1
            for session in sessions.values()
            if session.client == client and not session.finished
        )
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
        *,
        story: StoryPin | None = None,
        seed: int = 0,
    ) -> PracticeCreated:
        with self.repository.lock:
            self._admit(client, monotonic())
        try:
            # Bots may play before the human's first turn: outside the table lock.
            game = (
                SeededDuel(
                    OnlineGame.seeded(2, seed),
                    seed,
                    intent=story.intent,
                    route=story.route,
                    rival_budget=story.rival_budget,
                    rival_avoid_suit=story.rival_avoid_suit,
                    rival_expert=story.rival_expert,
                )
                if story
                else PracticeGame(seats, level, iterations=200)
            )
            update = GameUpdate.model_validate_json(game.snapshot())
            game_id, token = uuid4(), token_urlsafe(32)
            session = PracticeSession(
                game=game,
                token_digest=sha256(token.encode()).digest(),
                expires_at=monotonic() + self.settings.practice_session_ttl_seconds,
                client=client,
                story=story,
            )
            response = PracticeCreated(
                game_id=game_id,
                access_token=token,
                **update.model_dump(),
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

    def story_decision(self, game_id: UUID, token: str) -> tuple[StoryPin, SeededDuel]:
        with self.repository.lock:
            session = self._session(game_id, token)
        with session.lock:
            if session.story is None or not isinstance(session.game, SeededDuel):
                raise AppError(404, "story_not_found", "Story attempt not found")
            if not session.finished:
                raise AppError(409, "story_in_progress", "Finish the story duel first")
            return session.story, session.game

    def hint(self, game_id: UUID, token: str) -> PracticeHint:
        with self.repository.lock:
            game = self._session(game_id, token).game
        return hint_game(game, self.settings.practice_hint_iterations)

    def snapshot(self, game_id: UUID, token: str) -> GameUpdate:
        with self.repository.lock:
            return GameUpdate.model_validate_json(
                self._session(game_id, token).game.snapshot()
            )

    def play(
        self, game_id: UUID, token: str, command: PracticePlayRequest
    ) -> GameUpdate:
        with self.repository.lock:
            session = self._session(game_id, token)
        with session.lock:
            previous = session.plays.get(command.request_id)
            if previous is not None:
                validate_retry(previous.command, command)
                return previous.outcome
            next_game, update = play_game(session.game, command)
            session.plays[command.request_id] = RecordedPlay(command, update)
            session.game = next_game
            session.finished = update.view.outcome is not None
            return update
