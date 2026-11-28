from pydantic import BaseModel, Field

from app.modules.game.schemas.cards import Card, TableCard
from app.modules.game.schemas.events import Event
from app.modules.game.schemas.outcomes import Outcome
from app.modules.game.schemas.story import StoryObjective


class PlayerView(BaseModel):
    version: int
    turn: int | None
    outcome: Outcome | None
    card_counts: list[int]
    table: list[TableCard]
    escape_order: list[int]
    hand: list[Card]
    legal_moves: list[Card]


class GameUpdate(BaseModel):
    view: PlayerView
    events: list[Event]
    can_call_strike: bool | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    objective: StoryObjective | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
