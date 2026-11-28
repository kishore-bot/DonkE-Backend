from collections import Counter, OrderedDict, deque
from hashlib import sha256
from secrets import compare_digest
from threading import Lock
from time import monotonic
from uuid import UUID

from donke_engine import PracticeGame

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.game.dto.practice_session import PracticeSession
from app.modules.game.dto.story_pin import StoryPin
from app.modules.game.helpers.seeded_duel import SeededDuel


class PracticeRepository:
    def __init__(self) -> None:
        # Guards the session table only; never held while bots think.
        self._lock = Lock()
        self._sessions: dict[UUID, PracticeSession] = {}
        self._created: OrderedDict[str, deque[float]] = OrderedDict()
        self._creating: Counter[str] = Counter()

    def reserve(self, client: str, settings: Settings) -> None:
        with self._lock:
            self._admit(client, settings, monotonic())

    def _admit(self, client: str, settings: Settings, now: float) -> None:
        """Check capacity before running the engine. Called under the table lock."""
        sessions = self._sessions
        for game_id in [key for key, s in sessions.items() if s.expires_at <= now]:
            del sessions[game_id]
        created = self._created
        while created:
            oldest = next(iter(created.values()))
            if oldest[-1] > now - 60:
                break
            created.popitem(last=False)
        recent = created.get(client, deque())
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= settings.practice_creates_per_minute:
            raise AppError(
                429, "rate_limited", "Too many practice matches. Wait a minute"
            )
        creating = self._creating
        mine = sum(
            1
            for session in sessions.values()
            if session.client == client and not session.finished
        )
        if mine + creating[client] >= settings.practice_sessions_per_client:
            raise AppError(
                429, "practice_limit", "Finish one of your practice matches first"
            )
        self._evict_finished(settings.practice_max_sessions - creating.total())
        if len(sessions) + creating.total() >= settings.practice_max_sessions:
            raise AppError(503, "practice_full", "Practice is at capacity")
        recent.append(now)
        created[client] = recent
        created.move_to_end(client)
        creating[client] += 1

    def _evict_finished(self, room: int) -> None:
        """Drop finished matches, plain practice first and oldest first, until
        the table has fewer than `room` sessions. Finished matches only keep
        their result screen, so they never refuse a new match. O(n log n) for
        n <= practice_max_sessions, and only when the table is full."""
        sessions = self._sessions
        excess = len(sessions) - room + 1
        if excess <= 0:
            return
        finished = sorted(
            (session.story is not None, session.expires_at, game_id)
            for game_id, session in sessions.items()
            if session.finished
        )
        for *_, game_id in finished[:excess]:
            del sessions[game_id]

    def release(self, client: str) -> None:
        with self._lock:
            self._release(client)

    def _release(self, client: str) -> None:
        creating = self._creating
        creating[client] -= 1
        if creating[client] == 0:
            del creating[client]

    def save(
        self,
        game_id: UUID,
        client: str,
        token: str,
        game: PracticeGame | SeededDuel,
        story: StoryPin | None,
        ttl_seconds: int,
    ) -> None:
        with self._lock:
            self._sessions[game_id] = PracticeSession(
                game=game,
                token_digest=sha256(token.encode()).digest(),
                expires_at=monotonic() + ttl_seconds,
                client=client,
                story=story,
            )
            self._release(client)

    def get(self, game_id: UUID, token: str) -> PracticeSession:
        token_digest = sha256(token.encode()).digest()
        with self._lock:
            session = self._sessions.get(game_id)
            if (
                session is None
                or session.expires_at <= monotonic()
                or not compare_digest(session.token_digest, token_digest)
            ):
                raise AppError(404, "practice_not_found", "Practice match not found")
            return session
