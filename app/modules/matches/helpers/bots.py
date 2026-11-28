"""Bot seats in live matches: engine strength, persona style and rivals.

The Rust engine scores every legal move. A persona never plays a bad card:
it only chooses, in its own style, among moves within NEAR_BEST of the best.
No model call happens on the turn path, so bots stay fast and deterministic.
"""

import json
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

from donke_engine import OnlineGame

from app.modules.matches.schemas.persona import Persona
from app.modules.matches.schemas.state import GameSeat

PERSONAS: dict[Persona, str] = {
    "thug": "Kerala Thug",
    "professor": "The Professor",
    "aunty": "Gossip Aunty",
}


NEAR_BEST = 0.05
KNOWN_CUT_COST = 0.15


RANK_ORDER = [
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


def stable(*parts: object) -> int:
    return int.from_bytes(sha256(":".join(map(str, parts)).encode()).digest()[:8])


def persona_for(key: object) -> Persona:
    names: list[Persona] = ["thug", "professor", "aunty"]
    return names[stable("persona", key) % len(names)]


def strength(mmr: float) -> tuple[Literal["medium", "hard"], int]:
    """Bot level for the table: stronger tables get deeper search."""
    if mmr < 1300:
        return "medium", 0
    return "hard", int(min(400, max(100, 100 + (mmr - 1200) // 4)))


def assign(seats: list[GameSeat], mmrs: dict[UUID, int], game_id: UUID) -> int | None:
    """Give every bot seat a persona and strength. The first bot becomes the
    rival of the first human at the table. Returns the rival seat, if any."""
    humans = [seat for seat in seats if not seat.bot and seat.player_id]
    average = (
        sum(mmrs.get(seat.player_id, 1200) for seat in humans if seat.player_id)
        / len(humans)
        if humans
        else 1200
    )
    level, iterations = strength(average)
    rival_seat = None
    for index, seat in enumerate(seats):
        if not seat.bot:
            continue
        seat.level, seat.iterations = level, iterations
        if rival_seat is None and humans and humans[0].player_id:
            rival_seat = index
            seat.rival_of = humans[0].player_id
            seat.persona = persona_for(humans[0].player_id)
            seat.level = "hard"
            seat.iterations = max(iterations, 200)
            seat.display_name = f"{PERSONAS[seat.persona]} (Rival)"
        else:
            seat.persona = persona_for((game_id, index))
            seat.display_name = PERSONAS[seat.persona]
    return rival_seat


def choose(game: OnlineGame, seat: int, bot: GameSeat, seed: int) -> str:
    """The card JSON a bot seat plays now."""
    exposed = json.loads(game.exposed_leads(seat))
    if bot.level != "hard" or (bot.persona is None and not exposed):
        card = game.bot_move(seat, bot.level or "medium", bot.iterations, seed)
        assert card is not None, "the bot seat is to act"
        if exposed and json.loads(card) in exposed:
            legal = json.loads(game.view(seat))["legal_moves"]
            safer = [move for move in legal if move not in exposed]
            if safer:
                return json.dumps(
                    min(safer, key=lambda move: RANK_ORDER.index(move["rank"]))
                )
        return card
    scores: list[dict[str, Any]] = json.loads(game.evaluate(seat, bot.iterations, seed))
    # scores[0] is the engine's choice (most visited). A persona may pick any
    # move about as safe, but only among well-sampled ones: a move with a few
    # lucky playouts is not "near best", it is unknown.
    trusted = max(2, scores[0]["visits"] // 4)
    considered = [score for score in scores if score["visits"] >= trusted] or scores[:1]

    def safety(score: dict[str, Any]) -> float:
        return score["safe_rate"] - KNOWN_CUT_COST * (score["card"] in exposed)

    if exposed:
        considered.sort(key=safety, reverse=True)
    top = safety(considered[0])
    near = [score for score in considered if safety(score) >= top - NEAR_BEST]
    if bot.persona == "thug":
        # Loud and fearless: dumps the biggest card it safely can.
        pick = max(near, key=lambda score: RANK_ORDER.index(score["card"]["rank"]))
    elif bot.persona == "aunty":
        pick = near[seed % len(near)]  # Unpredictable, never reckless.
    else:
        pick = near[0]  # The Professor plays the engine's best.
    return json.dumps(pick["card"])


PERSONA_FLAVOR: dict[Persona, dict[str, str]] = {
    "thug": {
        "cut": "Vettu! Take the whole pile, friend.",
        "picked": "You think this scares me? I eat piles for breakfast.",
        "escaped": "Out! The Thug leaves no trace.",
    },
    "professor": {
        "cut": "A textbook Vettu. Please take notes.",
        "picked": "An instructive setback. Noted.",
        "escaped": "Escaped, exactly as calculated.",
    },
    "aunty": {
        "cut": "Ayyo, did I cut you? So sorry, dear!",
        "picked": "Don't tell anyone I picked these up!",
        "escaped": "I'm safe! Now, who will be the Donkey?",
    },
}


def persona_events(seat: int, bot: GameSeat, events: list[dict]) -> list[dict]:
    """A persona reacts to big moments in its own play, at most once a turn."""
    if bot.persona is None:
        return []
    for event in events:
        kind = event.get("event")
        moment = None
        if kind == "vettu" and event.get("cutter") == seat:
            moment = "cut"
        elif kind == "vettu" and event.get("receiver") == seat:
            moment = "picked"
        elif kind == "player_escaped" and event.get("seat") == seat:
            moment = "escaped"
        if moment:
            return [
                {
                    "event": "persona_line",
                    "seat": seat,
                    "persona": bot.persona,
                    "line": moment,
                }
            ]
    return []
