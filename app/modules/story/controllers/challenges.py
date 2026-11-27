from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import PlatformDep
from app.core.rate_limit import client_host, limit
from app.modules.game.dependencies import AccessToken, Practice
from app.modules.story.challenge import (
    ChallengeLink,
    ChallengeView,
    challenge_character,
    challenge_link,
    read_challenge,
)
from app.modules.story.chapters import (
    chapter_for,
)
from app.modules.story.schemas import StoryAttempt
from app.modules.story.services.duels import finished_duel, story_attempt

router = APIRouter()

ChallengeCode = Annotated[
    str, Path(min_length=48, max_length=768, pattern=r"^[A-Za-z0-9_.-]+$")
]


@router.post("/story/attempts/{game_id}/share")
async def share_attempt(
    game_id: UUID,
    token: AccessToken,
    practice: Practice,
    platform: PlatformDep,
    request: Request,
    response: Response,
) -> ChallengeLink:
    await limit(platform, "story_share", client_host(request), 15, 60)
    pin, duel = await finished_duel(practice, platform, game_id, token)
    response.headers["Cache-Control"] = "no-store"
    return challenge_link(platform, pin, duel)


@router.get("/story/challenges/{code}")
async def story_challenge(
    code: ChallengeCode,
    platform: PlatformDep,
    response: Response,
) -> ChallengeView:
    pin = read_challenge(platform, code)
    title, character = challenge_character(pin)
    response.headers["Cache-Control"] = "no-store"
    return ChallengeView(
        pack_title=title,
        rival=chapter_for(pin.pack_key, pin.chapter_id).rival,
        character=character,
        result=pin.result,
        expires_at=pin.exp,
    )


@router.post("/story/challenges/{code}/attempts", status_code=201)
async def play_challenge(
    code: ChallengeCode,
    practice: Practice,
    platform: PlatformDep,
    request: Request,
    response: Response,
) -> StoryAttempt:
    pin = read_challenge(platform, code)
    _, character = challenge_character(pin)
    chapter = chapter_for(pin.pack_key, pin.chapter_id)
    game = await run_in_threadpool(
        practice.create,
        2,
        client=client_host(request),
        story=pin.story(),
        seed=chapter.seed,
    )
    response.headers["Cache-Control"] = "no-store"
    return story_attempt(game, pin.story(), character, chapter)
