from pydantic import BaseModel

from app.modules.game.schemas.cards import Card
from app.modules.game.schemas.emotes import SceneEmote
from app.modules.game.schemas.practice import MoveScore


class SampledMove(MoveScore):
    visits: int


class StoryHighlight(BaseModel):
    version: str = "strike-review-v1"
    move: int
    card: Card
    legal_choices: int
    played_safe_rate: float
    alternative_safe_rate: float
    played_samples: int
    alternative_samples: int
    emote: SceneEmote
