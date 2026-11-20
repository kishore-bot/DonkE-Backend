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
    plays: dict[UUID, RecordedPlay] = field(default_factory=dict)


class PracticeRepository:
    def __init__(self) -> None:
        self.lock = Lock()
        self.sessions: dict[UUID, PracticeSession] = {}
