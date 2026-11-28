"""Post-duel review for a confirmed called Strike."""

from uuid import UUID

from donke_engine import OnlineGame
from pydantic import TypeAdapter
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.game.dto.decisions import StrikeDecision
from app.modules.game.schemas.cards import Card
from app.modules.game.schemas.emotes import SceneEmote
from app.modules.game.services.story_store import PIN, StoryStore
from app.modules.story.schemas.highlights import SampledMove, StoryHighlight

ITERATIONS = 768


MIN_VISITS = 16


MIN_SAFE_RATE = 0.80


MIN_ADVANTAGE = 0.12


TOP_TOLERANCE = 0.05


MOVES = TypeAdapter(list[SampledMove])


def analyse(decision: StrikeDecision, emote: SceneEmote) -> StoryHighlight | None:
    card = Card.model_validate_json(decision.card)
    game = OnlineGame.restore(decision.snapshot)
    estimates = MOVES.validate_json(game.evaluate(0, ITERATIONS, seed=decision.move))
    sampled = [score for score in estimates if score.visits >= MIN_VISITS]
    played = next((score for score in sampled if score.card == card), None)
    if played is None or played.safe_rate < MIN_SAFE_RATE or len(sampled) < 2:
        return None
    if (
        max(score.safe_rate for score in sampled) - played.safe_rate
        > TOP_TOLERANCE + 1e-9
    ):
        return None
    alternatives = [
        score
        for score in sampled
        if played.safe_rate - score.safe_rate >= MIN_ADVANTAGE
    ]
    if not alternatives:
        return None
    alternative = max(alternatives, key=lambda score: (score.safe_rate, score.visits))
    return StoryHighlight(
        move=decision.move,
        card=card,
        legal_choices=len(estimates),
        played_safe_rate=played.safe_rate,
        alternative_safe_rate=alternative.safe_rate,
        played_samples=played.visits,
        alternative_samples=alternative.visits,
        emote=emote,
    )


async def stored_highlight(
    platform: Platform, game_id: UUID, player_id: UUID
) -> StoryHighlight | None:
    store = StoryStore(platform)
    async with platform.sessions.begin() as db:
        duel = await store.load(
            db, game_id, store.token(game_id), lock=True, player=player_id
        )
        if not duel.finished:
            raise AppError(409, "story_in_progress", "Finish the story duel first")
        if duel.highlight is not None:
            return (
                StoryHighlight.model_validate(duel.highlight)
                if duel.highlight
                else None
            )
        candidate = duel.duel.get("strike_decision")
        result = (
            await run_in_threadpool(
                analyse,
                StrikeDecision(**candidate),
                PIN.validate_python(duel.pin).emote,
            )
            if candidate
            else None
        )
        duel.highlight = result.model_dump(mode="json") if result else {}
        return result
