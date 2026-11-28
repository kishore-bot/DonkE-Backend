from uuid import UUID

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import PlatformDep
from app.core.rate_limit import client_host
from app.modules.game.dependencies import Practice
from app.modules.identity.dependencies import (
    CurrentPlayer,
)
from app.modules.story.dependencies import StoryClock
from app.modules.story.schemas.archive import CollectionEntry
from app.modules.story.schemas.duel import StoryAttempt
from app.modules.story.services.archive import archive_attempt, collection
from app.modules.story.services.duels import story_attempt

router = APIRouter()


@router.get("/story/collection")
async def story_collection(
    player: CurrentPlayer,
    platform: PlatformDep,
    response: Response,
    clock: StoryClock,
) -> list[CollectionEntry]:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions() as db:
        return await collection(db, player.profile.id, clock())


@router.post("/story/collection/{season_id}/{chapter_id}/attempts", status_code=201)
async def start_archived_attempt(
    season_id: UUID,
    chapter_id: str,
    request: Request,
    response: Response,
    player: CurrentPlayer,
    platform: PlatformDep,
    practice: Practice,
    clock: StoryClock,
) -> StoryAttempt:
    async with platform.sessions() as db:
        pin, character, chapter = await archive_attempt(
            db, player.profile.id, season_id, chapter_id, clock()
        )
    game = await run_in_threadpool(
        practice.create, 2, client=client_host(request), story=pin, seed=chapter.seed
    )
    response.headers["Cache-Control"] = "no-store"
    return story_attempt(game, pin, character, chapter)
