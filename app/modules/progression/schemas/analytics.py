from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SeatStats(BaseModel):
    seat: int
    player_id: UUID | None
    bot: bool
    forfeited: bool
    plays: int = 0
    cuts_given: int = 0
    cuts_received: int = 0
    cards_picked: int = 0
    place: int | None = None
    donkey: bool = False
    badges: list[str] = []


class BiggestPile(BaseModel):
    receiver: int
    cards: int


class MatchAnalytics(BaseModel):
    id: UUID
    mode: str | None
    outcome: dict[str, Any]
    total_plays: int
    total_vettus: int
    biggest_pile: BiggestPile | None
    seats: list[SeatStats]
