"""Player insights from stored match analyses, and the Donkey roast card."""

from uuid import UUID

from app.core.errors import AppError
from app.modules.ai.helpers.coaching_analysis import SITUATIONS
from app.modules.ai.helpers.insights import (
    MIN_SITUATION_DECISIONS,
    NOT_ENOUGH,
    ROASTS,
    SITUATION_NAMES,
    SUMMARY,
    as_text,
    card_svg,
)
from app.modules.ai.helpers.prompts import PROMPTS
from app.modules.ai.schemas.coaching import Situation
from app.modules.ai.schemas.insights import Insights, Roast
from app.modules.ai.services.coaching import recent_analyses
from app.modules.ai.services.gateway import Gateway
from app.modules.ai.services.rewording import reword
from app.modules.identity.schemas.profile import Language
from app.modules.matches.schemas.results import MatchReplay
from app.modules.progression.services.analytics import match_analytics


async def insights(gateway: Gateway, player: UUID, language: Language) -> Insights:
    analyses = await recent_analyses(gateway, player)
    totals: dict[Situation, list[int]] = {name: [0, 0] for name in SITUATIONS}
    decisions = good_weighted = 0.0
    for analysis in analyses:
        decisions += analysis.decisions
        good_weighted += analysis.accuracy * analysis.decisions
        for name, stats in analysis.situations.items():
            totals[name][0] += stats.decisions
            totals[name][1] += stats.mistakes
    rates: dict[Situation, float] = {
        name: round(mistakes / count, 3)
        for name, (count, mistakes) in totals.items()
        if count >= MIN_SITUATION_DECISIONS
    }
    strongest = min(rates, key=lambda name: (rates[name], name)) if rates else None
    focus = max(rates, key=lambda name: (rates[name], name)) if rates else None
    accuracy = round(good_weighted / decisions, 3) if decisions else None
    if accuracy is None or strongest is None or focus is None or strongest == focus:
        return Insights(
            matches=len(analyses),
            decisions=int(decisions),
            accuracy=accuracy,
            strongest=strongest,
            focus=None if strongest == focus else focus,
            mistake_rates=rates,
            summary=NOT_ENOUGH[language],
            source="template",
        )
    names = SITUATION_NAMES[language]
    fact = SUMMARY[language].format(
        matches=len(analyses),
        accuracy=round(accuracy * 100),
        strong=names[strongest],
        focus=names[focus],
    )
    cache = gateway.key(
        f"insight:{PROMPTS['insight'].label}:{player}:{language}:{len(analyses)}"
    )
    redis = gateway.platform.redis
    if cached := await redis.get(cache):
        text, source = as_text(cached), "gemini"
    else:
        text, source = await reword(gateway, "insight", fact, language, words=45)
        if source == "gemini":
            await redis.set(cache, text, ex=86400)
    return Insights(
        matches=len(analyses),
        decisions=int(decisions),
        accuracy=accuracy,
        strongest=strongest,
        focus=focus,
        mistake_rates=rates,
        summary=text,
        source=source,
    )


async def roast(gateway: Gateway, replay: MatchReplay, language: Language) -> Roast:
    stats = match_analytics(replay)
    loser = next((seat for seat in stats.seats if seat.donkey), None)
    if loser is None:
        raise AppError(404, "no_donkey", "Everyone escaped this match")
    name = replay.seats[loser.seat].display_name
    fact = ROASTS[language].format(
        name=name, cards=loser.cards_picked, cuts=loser.cuts_received
    )
    cache = gateway.key(f"roast:{PROMPTS['roast'].label}:{replay.id}:{language}")
    redis = gateway.platform.redis
    if cached := await redis.get(cache):
        text, source = as_text(cached), "gemini"
    else:
        text, source = await reword(
            gateway, "roast", fact, language, words=35, keep=(name,), name=name
        )
        if source == "gemini":
            await redis.set(cache, text, ex=7 * 86400)
    return Roast(donkey=name, text=text, source=source, svg=card_svg(name, text))
