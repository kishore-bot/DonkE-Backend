import json

from donke_engine import OnlineGame
from pydantic import BaseModel

from app.modules.game.repository import StoryPin
from app.modules.game.schemas import Card
from app.modules.game.seeded import SeededDuel


class RivalEvidence(BaseModel):
    intent: str
    source: str
    card: Card
    candidate_count: int
    played_safe_rate: float
    best_safe_rate: float


class DuelCoach(BaseModel):
    evidence: RivalEvidence | None = None
    answer: str
    citation: str | None = None


def explain(pin: StoryPin, duel: SeededDuel) -> DuelCoach:
    decision = duel.decision
    if decision is None:
        return DuelCoach(
            answer="The recorded duel did not contain a rival decision with multiple legal cards."
        )
    card = Card.model_validate_json(decision.card)
    game = OnlineGame.restore(decision.snapshot)
    scores = json.loads(game.evaluate(1, 120, duel.seed))
    chosen = next(score for score in scores if score["card"] == card.model_dump())
    return DuelCoach(
        answer="The rival's first decision with multiple legal cards was replayed and scored by the engine.",
        citation="rival-first-choice",
        evidence=RivalEvidence(
            intent=pin.intent,
            source=pin.intent_source,
            card=card,
            candidate_count=len(scores),
            played_safe_rate=chosen["safe_rate"],
            best_safe_rate=max(score["safe_rate"] for score in scores),
        ),
    )
