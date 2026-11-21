from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from uuid import UUID

from donke_engine import PracticeGame

from app.modules.game.schemas import Card, GameUpdate


@dataclass(frozen=True, slots=True)
class RecordedPlay:
    version: int
    card: Card
    outcome: GameUpdate


@dataclass(slots=True)
class PracticeSession:
    game: PracticeGame
    token_digest: bytes
    expires_at: float
    client: str = "unknown"
    plays: dict[UUID, RecordedPlay] = field(default_factory=dict)
    # Serialises plays within one match; other matches never wait on it.
    lock: Lock = field(default_factory=Lock)


class PracticeRepository:
    def __init__(self) -> None:
        # Guards the session table only; never held while bots think.
        self.lock = Lock()
        self.sessions: dict[UUID, PracticeSession] = {}
        self.created: dict[str, deque[float]] = {}
