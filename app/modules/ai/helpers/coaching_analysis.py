import json
from typing import Any

from donke_engine import OnlineGame

from app.core.errors import AppError
from app.modules.ai.schemas.coaching import (
    Analysis,
    Decision,
    Sample,
    Situation,
    SituationStats,
)
from app.modules.identity.schemas.profile import Language
from app.modules.matches.schemas.results import MatchReplay

ITERATIONS = 200


GOOD_GAP = 0.03


MISTAKE_GAP = 0.15


TOP_MISTAKES = 3


SITUATIONS: tuple[Situation, ...] = ("leading", "following", "cutting", "near_escape")


RANKS = {
    "Two": "2",
    "Three": "3",
    "Four": "4",
    "Five": "5",
    "Six": "6",
    "Seven": "7",
    "Eight": "8",
    "Nine": "9",
    "Ten": "10",
    "Jack": "J",
    "Queen": "Q",
    "King": "K",
    "Ace": "A",
}


SUITS = {"Spades": "♠", "Hearts": "♥", "Diamonds": "♦", "Clubs": "♣"}


def label(card: dict[str, Any]) -> str:
    return RANKS[card["rank"]] + SUITS[card["suit"]]


TIPS: dict[Language, str] = {
    "en": "Move {move}: you played {played}, but {best} was safer ({best_pct}% vs {played_pct}%).",
    "ml": "നീക്കം {move}: നിങ്ങൾ {played} ഇട്ടു, പക്ഷേ {best} കൂടുതൽ സുരക്ഷിതമായിരുന്നു ({best_pct}% / {played_pct}%).",
    "ta": "நகர்வு {move}: நீங்கள் {played} போட்டீர்கள், ஆனால் {best} பாதுகாப்பானது ({best_pct}% / {played_pct}%).",
    "hi": "चाल {move}: आपने {played} चला, लेकिन {best} ज़्यादा सुरक्षित था ({best_pct}% / {played_pct}%)।",
    "kn": "ನಡೆ {move}: ನೀವು {played} ಆಡಿದಿರಿ, ಆದರೆ {best} ಹೆಚ್ಚು ಸುರಕ್ಷಿತವಾಗಿತ್ತು ({best_pct}% / {played_pct}%).",
    "te": "ఎత్తు {move}: మీరు {played} వేశారు, కానీ {best} మరింత సురక్షితం ({best_pct}% / {played_pct}%).",
}


def situation(view: dict[str, Any]) -> Situation:
    if len(view["hand"]) <= 2:
        return "near_escape"
    table = view["table"]
    if not table:
        return "leading"
    lead = table[0]["card"]["suit"]
    if any(card["suit"] == lead for card in view["legal_moves"]):
        return "following"
    return "cutting"


def analyse(replay: MatchReplay, seat: int, iterations: int = ITERATIONS) -> Analysis:
    """Score every real choice `seat` made. CPU bound; run it off the loop."""
    if replay.opening is None:
        raise AppError(
            404, "analysis_unavailable", "This match was played before analysis"
        )
    game = OnlineGame.restore(replay.opening)
    decisions: list[Decision] = []
    samples: list[Sample] = []
    move = 0
    for batch in replay.events:
        for event in batch.events:
            if event.get("event") != "card_played":
                continue
            move += 1
            card = event["card"]
            if event["seat"] == seat and not event.get("auto"):
                view = json.loads(game.view(seat))
                if len(view["legal_moves"]) >= 2:
                    scores = json.loads(game.evaluate(seat, iterations, seed=move))
                    best = scores[0]
                    chosen = next(
                        (score for score in scores if score["card"] == card), None
                    )
                    if chosen is not None:
                        samples.append(
                            Sample(
                                think_ms=event.get("think_ms"),
                                legal=len(view["legal_moves"]),
                                # The engine's choice is its most visited move.
                                top=chosen["card"] == best["card"],
                            )
                        )
                        decisions.append(
                            Decision(
                                move=move,
                                situation=situation(view),
                                played=label(card),
                                best=label(best["card"]),
                                played_rate=chosen["safe_rate"],
                                best_rate=best["safe_rate"],
                            )
                        )
            try:
                game.play(event["seat"], json.dumps(card))
            except ValueError as error:
                raise AppError(
                    409, "analysis_mismatch", "The replay does not match its deal"
                ) from error
    situations: dict[Situation, SituationStats] = {
        name: SituationStats() for name in SITUATIONS
    }
    for decision in decisions:
        stats = situations[decision.situation]
        stats.decisions += 1
        stats.mistakes += int(decision.gap >= MISTAKE_GAP)
    good = sum(decision.gap <= GOOD_GAP for decision in decisions)
    mistakes = sorted(
        (decision for decision in decisions if decision.gap >= MISTAKE_GAP),
        key=lambda decision: (-decision.gap, decision.move),
    )[:TOP_MISTAKES]
    return Analysis(
        decisions=len(decisions),
        accuracy=round(good / len(decisions), 3) if decisions else 1.0,
        mistakes=mistakes,
        situations=situations,
        samples=samples,
    )
