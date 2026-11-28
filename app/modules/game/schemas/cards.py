from typing import Literal

from pydantic import BaseModel, ConfigDict

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


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suit: Suit
    rank: Rank


class TableCard(BaseModel):
    seat: int
    card: Card
