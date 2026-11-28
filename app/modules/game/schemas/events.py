from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.modules.game.schemas.cards import Card, TableCard
from app.modules.game.schemas.outcomes import Outcome


class CardPlayed(BaseModel):
    event: Literal["card_played"]
    seat: int
    card: Card


class TrickDiscarded(BaseModel):
    event: Literal["trick_discarded"]
    leader: int
    pile: list[TableCard]


class Vettu(BaseModel):
    event: Literal["vettu"]
    cutter: int
    receiver: int
    pile: list[TableCard]


class PlayerEscaped(BaseModel):
    event: Literal["player_escaped"]
    seat: int
    place: int


class GameFinished(BaseModel):
    event: Literal["game_finished"]
    outcome: Outcome


class StrikeCalled(BaseModel):
    event: Literal["strike_called"]
    target: Literal[1]


class StrikeCallResolved(BaseModel):
    event: Literal["strike_call_resolved"]
    success: bool


Event = Annotated[
    CardPlayed
    | TrickDiscarded
    | Vettu
    | PlayerEscaped
    | GameFinished
    | StrikeCalled
    | StrikeCallResolved,
    Field(discriminator="event"),
]
