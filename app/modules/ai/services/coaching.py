"""Engine-grounded coaching: re-play a finished match from its opening deal,
score each of the player's real choices with the Rust engine, and turn the
biggest mistakes into tips. Gemini only rewords the tip sentences."""

import asyncio
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.ai.helpers.coaching_analysis import TIPS, analyse
from app.modules.ai.helpers.prompts import PROMPTS
from app.modules.ai.models.match_analysis import MatchAnalysis
from app.modules.ai.schemas.coaching import Analysis, Coaching, Tip
from app.modules.ai.services.gateway import Gateway
from app.modules.ai.services.rewording import reword
from app.modules.identity.schemas.profile import Language
from app.modules.matches.schemas.results import MatchReplay


def seat_of(replay: MatchReplay, player: UUID) -> int:
    for index, seat in enumerate(replay.seats):
        if seat.player_id == player:
            return index
    raise AppError(404, "game_not_found", "Match replay not found")


async def stored_analysis(
    platform: Platform, replay: MatchReplay, player: UUID
) -> Analysis:
    async with platform.sessions() as db:
        row = await db.get(MatchAnalysis, (replay.id, player))
    if row is not None:
        return Analysis.model_validate(row.payload)
    seat = seat_of(replay, player)
    result = await asyncio.to_thread(analyse, replay, seat)
    async with platform.sessions.begin() as db:
        await db.execute(
            insert(MatchAnalysis)
            .values(
                game_id=replay.id,
                player_id=player,
                decisions=result.decisions,
                accuracy=result.accuracy,
                payload=result.model_dump(mode="json"),
            )
            .on_conflict_do_nothing()
        )
    return result


async def coaching(
    gateway: Gateway, replay: MatchReplay, player: UUID, language: Language
) -> Coaching:
    result = await stored_analysis(gateway.platform, replay, player)
    cache = gateway.key(f"tips:{PROMPTS['tip'].label}:{replay.id}:{player}:{language}")
    redis = gateway.platform.redis
    if cached := await redis.get(cache):
        tips = [Tip.model_validate(item) for item in json.loads(cached)]
    else:
        tips = []
        for mistake in result.mistakes:
            fact = TIPS[language].format(
                move=mistake.move,
                played=mistake.played,
                best=mistake.best,
                best_pct=round(mistake.best_rate * 100),
                played_pct=round(mistake.played_rate * 100),
            )
            text, source = await reword(gateway, "tip", fact, language, words=40)
            tips.append(Tip(move=mistake.move, text=text, source=source))
        await redis.set(cache, json.dumps([tip.model_dump() for tip in tips]), ex=86400)
    return Coaching(
        game_id=replay.id, tips=tips, **result.model_dump(exclude={"samples"})
    )


async def recent_analyses(
    gateway: Gateway, player: UUID, limit: int = 20
) -> list[Analysis]:
    async with gateway.platform.sessions() as db:
        rows = await db.scalars(
            select(MatchAnalysis)
            .where(MatchAnalysis.player_id == player)
            .order_by(MatchAnalysis.created_at.desc())
            .limit(limit)
        )
        return [Analysis.model_validate(row.payload) for row in rows]
