from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
from threading import Lock
from uuid import UUID

from donke_engine import PracticeGame

from app.modules.game.schemas import Card, GameUpdate
from app.modules.game.seeded import SeededDuel


@dataclass(frozen=True, slots=True)
class RecordedPlay:
    version: int
    card: Card
    outcome: GameUpdate
    call_strike: bool = False


@dataclass(frozen=True, slots=True)
class StoryPin:
    season_id: UUID
    pack_key: str
    character_id: str
    player_id: UUID | None


@dataclass(slots=True)
class PracticeSession:
    game: PracticeGame | SeededDuel
    token_digest: bytes
    expires_at: float
    client: str = "unknown"
    story: StoryPin | None = None
    finished: bool = False
    plays: dict[UUID, RecordedPlay] = field(default_factory=dict)
    # Serialises plays within one match; other matches never wait on it.
    lock: Lock = field(default_factory=Lock)


class PracticeRepository:
    def __init__(self) -> None:
        # Guards the session table only; never held while bots think.
        self.lock = Lock()
        self.sessions: dict[UUID, PracticeSession] = {}
        self.created: OrderedDict[str, deque[float]] = OrderedDict()
        self.creating: Counter[str] = Counter()
