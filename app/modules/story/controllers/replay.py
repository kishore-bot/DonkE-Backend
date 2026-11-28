from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import PlatformDep
from app.core.rate_limit import client_host, limit
from app.modules.ai.dependencies import AI
from app.modules.ai.services.rule_index import ranked_rules
from app.modules.game.dependencies import AccessToken, Practice
from app.modules.game.schemas.story import StoryEvent
from app.modules.identity.dependencies import (
    CurrentPlayer,
)
from app.modules.story.schemas.coach import DuelCoach
from app.modules.story.schemas.highlights import StoryHighlight
from app.modules.story.services.coach import explain, grounded_replay
from app.modules.story.services.duels import finished_duel
from app.modules.story.services.highlights import stored_highlight

router = APIRouter()


@router.get("/story/attempts/{game_id}/highlight")
async def story_highlight(
    game_id: UUID, player: CurrentPlayer, platform: PlatformDep, response: Response
) -> StoryHighlight | None:
    actor = player.profile.id
    await limit(platform, "story_highlight", str(actor), 15, 60)
    response.headers["Cache-Control"] = "no-store"
    return await stored_highlight(platform, game_id, actor)


@router.get("/story/attempts/{game_id}/events")
async def story_events(
    game_id: UUID,
    token: AccessToken,
    practice: Practice,
    platform: PlatformDep,
    response: Response,
    request: Request,
) -> tuple[StoryEvent, ...]:
    await limit(platform, "story_coach", client_host(request), 15, 60)
    _, duel = await finished_duel(practice, platform, game_id, token)
    response.headers["Cache-Control"] = "no-store"
    return duel.journal


@router.get("/story/attempts/{game_id}/coach")
async def story_coach(
    game_id: UUID,
    request: Request,
    response: Response,
    token: AccessToken,
    practice: Practice,
    gateway: AI,
    question: Annotated[str | None, Query(min_length=2, max_length=240)] = None,
    sequence: Annotated[int | None, Query(ge=1)] = None,
) -> DuelCoach:
    await limit(gateway.platform, "story_coach", client_host(request), 15, 60)
    pin, duel = await finished_duel(practice, gateway.platform, game_id, token)
    response.headers["Cache-Control"] = "no-store"
    if grounded := grounded_replay(duel.journal, question, sequence):
        return grounded
    if question is None:
        return await run_in_threadpool(explain, pin, duel)
    rules = await ranked_rules(gateway, question)
    if not rules:
        return DuelCoach(
            answer="I could not find evidence for that question in the game rules."
        )
    rule = rules[0]
    return DuelCoach(answer=rule.en, citation=f"rule:{rule.source}")
