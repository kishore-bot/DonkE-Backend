"""Typed, public play facts scoped to a finished attempt."""

import re

from app.modules.game.schemas import StoryEvent


def replay_summary(event: StoryEvent) -> str:
    seat = f"Seat {event.seat + 1}" if event.seat is not None else "A player"
    recipient = (
        f"seat {event.recipient + 1}"
        if event.recipient is not None
        else "the recipient"
    )
    match event.kind:
        case "strike":
            return f"{seat} landed a Strike. {recipient.capitalize()} picked up {event.cards} cards."
        case "escaped":
            return f"{seat} escaped."
        case "finished":
            return "The duel ended."
        case "strike_called":
            return f"{seat} called a Strike against {recipient}."
        case "strike_resolved":
            return (
                "The called Strike succeeded."
                if event.success
                else "The called Strike expired or missed."
            )


def at_sequence(events: tuple[StoryEvent, ...], sequence: int) -> StoryEvent | None:
    if 1 <= sequence <= len(events):
        event = events[sequence - 1]
        if event.sequence == sequence:
            return event
    return None


def requested_sequence(question: str | None) -> int | None:
    if question is None:
        return None
    match = re.search(
        r"\b(?:replay|event)\s*[:#]?\s*(\d{1,6})\b", question, re.IGNORECASE
    )
    return int(match[1]) if match else None


def asks_for_private_state(question: str | None) -> bool:
    return bool(
        question
        and re.search(
            r"\b(?:hidden cards?|hidden hand|private hands?|unplayed cards?|access token|draw seed|deal seed)\b",
            question,
            re.IGNORECASE,
        )
    )
