from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

type Suit = Literal["Clubs", "Diamonds", "Hearts", "Spades"]
type Rank = Literal[
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Jack",
    "Queen",
    "King",
    "Ace",
]

type EmoteMotion = Literal["resolve", "salute", "flourish"]


class SceneEmote(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str | None = None
    title: str = "Standard celebration"
    motion: EmoteMotion = "resolve"


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suit: Suit
    rank: Rank


class TableCard(BaseModel):
    seat: int
    card: Card


class DonkeyOutcome(BaseModel):
    reason: Literal["donkey"]
    seat: int


class AllSafeOutcome(BaseModel):
    reason: Literal["all_safe"]


class PlayLimitOutcome(BaseModel):
    reason: Literal["play_limit"]


Outcome = Annotated[
    DonkeyOutcome | AllSafeOutcome | PlayLimitOutcome,
    Field(discriminator="reason"),
]


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


class PracticeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seats: int = Field(default=4, ge=2, le=5, strict=True)
    level: Literal["easy", "medium", "hard"] = "medium"


class MoveScore(BaseModel):
    card: Card
    safe_rate: float


class PracticeHint(BaseModel):
    """Engine scores for the human's legal moves, best first."""

    best: Card | None
    options: list[MoveScore]


class PracticeCreated(GameUpdate):
    game_id: UUID
    access_token: str


class PlayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_version: int = Field(ge=0, strict=True)
    card: Card


class PracticePlayRequest(PlayRequest):
    call_strike: bool = Field(default=False, strict=True)
