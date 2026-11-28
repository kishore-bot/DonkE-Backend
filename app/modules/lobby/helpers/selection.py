"""Skill-aware table selection for the matchmaking worker.

The queue head is read without taking anything, hidden skill and blocks are
loaded from Postgres, and the Rust `select_table` picks the table: built
around the longest waiter, inside a skill window that widens with waiting,
never seating players who blocked each other, parties kept whole. The Lua
claim then takes exactly those players atomically, re-checking each one.
"""

import json
from typing import Protocol
from uuid import UUID

from donke_engine import select_table

# Skill window in hidden-skill (mu) units, matching the Rust defaults.
BASE_WINDOW = 6.0
WINDOW_PER_SECOND = 0.5
OPEN_AFTER_SECONDS = 30.0


class TableFacts(Protocol):
    """Loads hidden skill (mu) and block pairs for queued players."""

    async def load(
        self, players: list[UUID]
    ) -> tuple[dict[UUID, float], list[tuple[str, str]]]: ...


def choose(
    entries: list[dict],
    now_ms: int,
    skills: dict[UUID, float],
    avoid: list[tuple[str, str]],
    seats: int,
    bot_wait_seconds: float,
) -> list[str] | None:
    """The chosen player ids, anchor first, or None to keep waiting."""
    candidates = [
        {
            "id": entry["player_id"],
            "wait_seconds": max(0.0, (now_ms - entry["since"]) / 1000),
            "skill": skills.get(UUID(entry["player_id"]), 25.0),
            "party": entry.get("party"),
        }
        for entry in entries
    ]
    oldest = max((candidate["wait_seconds"] for candidate in candidates), default=0)
    # Bots fill the rest once the longest waiter has waited long enough.
    min_humans = 1 if oldest >= bot_wait_seconds else seats
    config = {
        "min_humans": min_humans,
        "max_seats": seats,
        "base_window": BASE_WINDOW,
        "window_per_second": WINDOW_PER_SECOND,
        "open_after_seconds": OPEN_AFTER_SECONDS,
        "avoid": avoid,
    }
    return select_table(json.dumps(candidates), json.dumps(config))
