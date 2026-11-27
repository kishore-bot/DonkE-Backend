from uuid import UUID

from fastapi import APIRouter

from app.core.rate_limit import limit
from app.modules.ai.coaching import Coaching, coaching
from app.modules.ai.dependencies import AI
from app.modules.ai.index import ranked_rules
from app.modules.ai.insights import Insights, Roast, insights, roast
from app.modules.ai.knowledge import NO_MATCH
from app.modules.ai.rivals import PersonaLines, RivalView, persona_lines, rival
from app.modules.ai.schemas import (
    CoachReply,
    CoachRequest,
)
from app.modules.identity.dependencies import CurrentPlayer
from app.modules.matches.settlement import read_replay

router = APIRouter()


@router.post("/coach/ask")
async def ask(body: CoachRequest, player: CurrentPlayer, gateway: AI) -> CoachReply:
    await limit(gateway.platform, "coach", str(player.profile.id), 20, 60)
    results = await ranked_rules(gateway, body.question)
    language = player.profile.language
    if not results:
        return CoachReply(answer=NO_MATCH[language], source="no_match")
    candidates = "\n".join(f"{rule.source}: {rule.en}" for rule in results)
    chosen = await gateway.select(
        "coach",
        f"Pick the best rule for this question: {body.question}\nCandidate rules:\n{candidates}",
        {rule.source for rule in results},
    )
    rule = next((item for item in results if item.source == chosen), results[0])
    return CoachReply(
        answer=rule.answer(language),
        citation=rule.source,
        source="gemini_selected" if chosen else "rules",
    )


@router.get("/games/{game_id}/analysis")
async def analysis(game_id: UUID, player: CurrentPlayer, gateway: AI) -> Coaching:
    """Engine review of your real choices in a finished match, with tips."""
    await limit(gateway.platform, "analysis", str(player.profile.id), 10, 60)
    replay = await read_replay(gateway.platform, game_id, player.profile.id)
    return await coaching(gateway, replay, player.profile.id, player.profile.language)


@router.get("/coach/insights")
async def coach_insights(player: CurrentPlayer, gateway: AI) -> Insights:
    return await insights(gateway, player.profile.id, player.profile.language)


@router.get("/games/{game_id}/roast")
async def donkey_roast(game_id: UUID, player: CurrentPlayer, gateway: AI) -> Roast:
    """A playful share card for the match's Donkey."""
    await limit(gateway.platform, "roast", str(player.profile.id), 20, 60)
    replay = await read_replay(gateway.platform, game_id, player.profile.id)
    return await roast(gateway, replay, player.profile.language)


@router.get("/rival")
async def my_rival(player: CurrentPlayer, gateway: AI) -> RivalView:
    """Your persistent rival bot, its record against you, and a taunt."""
    return await rival(gateway, player.profile.id, player.profile.language)


@router.get("/personas/lines")
async def lines(player: CurrentPlayer, gateway: AI) -> PersonaLines:
    """Text for `persona_line` match events in your language."""
    return await persona_lines(gateway, player.profile.language)
