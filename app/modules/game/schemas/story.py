from typing import Literal

from pydantic import BaseModel

from app.modules.game.schemas.cards import Suit

type StoryRoute = Literal["seal", "reef", "storm"]


class StoryObjective(BaseModel):
    route: StoryRoute
    count: int
    target: int
    met: bool


class StoryEvent(BaseModel):
    sequence: int
    move: int
    kind: Literal["strike", "escaped", "finished", "strike_called", "strike_resolved"]
    seat: int | None = None
    recipient: int | None = None
    cards: int | None = None
    led_suit: Suit | None = None
    success: bool | None = None
