from dataclasses import dataclass, field
from threading import Lock
from uuid import UUID

from donke_engine import PracticeGame

from app.modules.game.dto.story_pin import StoryPin
from app.modules.game.helpers.seeded_duel import SeededDuel
from app.modules.game.schemas.practice import PracticeHint, PracticePlayRequest
from app.modules.game.schemas.views import GameUpdate


@dataclass(frozen=True, slots=True)
class RecordedPlay:
    command: PracticePlayRequest
    outcome: GameUpdate


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
    # The last hint and the game instance it was computed for. Play publishes a
    # new instance, so one engine search serves every hint request per position.
    hint: tuple[object, PracticeHint] | None = None
    hint_lock: Lock = field(default_factory=Lock)
