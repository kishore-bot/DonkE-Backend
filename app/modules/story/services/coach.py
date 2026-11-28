import json

from donke_engine import OnlineGame

from app.modules.game.dto.story_pin import StoryPin
from app.modules.game.helpers.seeded_duel import SeededDuel
from app.modules.game.schemas.cards import Card
from app.modules.game.schemas.story import StoryEvent
from app.modules.story.helpers.replay import (
    asks_for_private_state,
    at_sequence,
    replay_summary,
    requested_sequence,
)
from app.modules.story.schemas.coach import DuelCoach, RivalEvidence


def grounded_replay(
    events: tuple[StoryEvent, ...], question: str | None, sequence: int | None
) -> DuelCoach | None:
    if asks_for_private_state(question):
        return DuelCoach(
            answer="The coach can cite public recorded events and game rules."
        )
    sequence = sequence if sequence is not None else requested_sequence(question)
    if sequence is None:
        return None
    event = at_sequence(events, sequence)
    if event is None:
        return DuelCoach(answer="That event was not recorded in this duel.")
    return DuelCoach(
        answer=replay_summary(event),
        citation=f"replay:{event.sequence}",
        replay_event=event,
    )


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
