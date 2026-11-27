from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal
from uuid import UUID

from donke_engine import PracticeGame

from app.modules.game.schemas import (
    GameUpdate,
    PracticePlayRequest,
    SceneEmote,
    StoryEvent,
    StoryRoute,
    Suit,
)
from app.modules.game.seeded import RivalIntent, SeededDuel


@dataclass(frozen=True, slots=True)
class RecordedPlay:
    command: PracticePlayRequest
    outcome: GameUpdate


@dataclass(frozen=True, slots=True)
class StoryPin:
    season_id: UUID
    pack_key: str
    character_id: str
    player_id: UUID | None
    intent: RivalIntent = "steady"
    intent_source: Literal["gemini", "engine"] = "engine"
    squad_party_id: UUID | None = None
    chapter_id: str = "trial"
    emote: SceneEmote = field(default_factory=SceneEmote)
    route: StoryRoute | None = None
    rival_budget: int | None = None
    target_rating: int | None = None
    remembered: StoryEvent | None = None
    rival_avoid_suit: Suit | None = None
    rival_expert: bool = False


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
