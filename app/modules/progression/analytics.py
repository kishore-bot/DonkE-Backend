"""Per-seat match statistics computed from a stored replay.

The replay is the single source of truth: settlement uses these numbers for
lifetime stats and achievements, and players read them after a match.
"""

from collections.abc import Iterator
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.modules.matches.schemas import MatchReplay


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


BADGES = {
    "vettu_king": ("cuts_given", "Most Vettus given"),
    "pile_magnet": ("cards_picked", "Picked up the most cards"),
}


def events(replay: MatchReplay) -> Iterator[dict[str, Any]]:
    for batch in replay.events:
        yield from batch.events


def match_analytics(replay: MatchReplay) -> MatchAnalytics:
    seats = [
        SeatStats(
            seat=index,
            player_id=seat.player_id,
            bot=seat.bot,
            forfeited=seat.forfeited,
        )
        for index, seat in enumerate(replay.seats)
    ]
    total_plays = total_vettus = 0
    biggest: BiggestPile | None = None

    def at(index: Any) -> SeatStats | None:
        # Replays are stored data; never let a bad seat index break settlement.
        if isinstance(index, int) and 0 <= index < len(seats):
            return seats[index]
        return None

    for event in events(replay):
        kind = event.get("event")
        if kind == "card_played" and (player := at(event.get("seat"))):
            player.plays += 1
            total_plays += 1
        elif kind == "vettu":
            total_vettus += 1
            if cutter := at(event.get("cutter")):
                cutter.cuts_given += 1
            if receiver := at(event.get("receiver")):
                receiver.cuts_received += 1
                size = len(event.get("pile", []))
                receiver.cards_picked += size
                if biggest is None or size > biggest.cards:
                    biggest = BiggestPile(receiver=receiver.seat, cards=size)
        elif kind == "player_escaped" and (player := at(event.get("seat"))):
            player.place = event.get("place")
    if replay.outcome.get("reason") == "donkey" and (
        loser := at(replay.outcome.get("seat"))
    ):
        loser.donkey = True

    for badge, (attribute, _) in BADGES.items():
        best = max((getattr(seat, attribute) for seat in seats), default=0)
        leaders = [seat for seat in seats if getattr(seat, attribute) == best]
        if best > 0 and len(leaders) == 1:
            leaders[0].badges.append(badge)

    return MatchAnalytics(
        id=replay.id,
        mode=replay.mode,
        outcome=replay.outcome,
        total_plays=total_plays,
        total_vettus=total_vettus,
        biggest_pile=biggest,
        seats=seats,
    )


def finishing_ranks(analytics: MatchAnalytics) -> dict[int, int]:
    """Rank per seat, 1 is best. Escapes rank by place, then seats still
    holding cards tie, then the Donkey, then players who left."""
    seats = analytics.seats
    escaped = [seat for seat in seats if seat.place is not None]
    ranks = {seat.seat: seat.place for seat in escaped if seat.place is not None}
    holding = len(escaped) + 1
    for seat in seats:
        if seat.seat in ranks:
            continue
        if seat.forfeited:
            ranks[seat.seat] = len(seats) + 1
        elif seat.donkey:
            ranks[seat.seat] = len(seats)
        else:
            ranks[seat.seat] = holding
    return ranks
