from uuid import UUID

from fastapi import APIRouter, Request, Response

from app.core.dependencies import PlatformDep
from app.core.errors import AppError
from app.core.rate_limit import client_host
from app.modules.ai.dependencies import AI
from app.modules.game.dependencies import Practice
from app.modules.game.services.story_store import StoryStore
from app.modules.identity.dependencies import (
    CurrentPlayer,
    OptionalPlayer,
)
from app.modules.progression.helpers.season_content import PACKS
from app.modules.progression.services.seasons import active_manifest
from app.modules.story.dependencies import StoryClock
from app.modules.story.helpers.chapters import CHAPTERS, chapter_for
from app.modules.story.schemas.chapters import ChapterView
from app.modules.story.schemas.duel import StartDuel, StoryAttempt
from app.modules.story.services.chapters import cleared_chapters, describe
from app.modules.story.services.duels import start_attempt, story_attempt

router = APIRouter()


@router.get("/seasons/{season_id}/story/chapters")
async def campaign(
    season_id: UUID,
    platform: PlatformDep,
    response: Response,
    player: OptionalPlayer,
    clock: StoryClock,
) -> list[ChapterView]:
    player_id = player.profile.id if player else None
    now = clock()
    async with platform.sessions() as db:
        manifest = await active_manifest(db, now)
        if manifest is None or manifest.season_id != season_id:
            raise AppError(404, "story_unavailable", "This story season is unavailable")
        cleared = await cleared_chapters(db, season_id, player_id)
    response.headers["Cache-Control"] = "no-store"
    return [
        describe(manifest, chapter, player_id, cleared, now)
        for chapter in CHAPTERS.get(manifest.pack_key, ())
    ]


@router.post("/story/attempts", status_code=201)
async def start_duel(
    body: StartDuel,
    request: Request,
    response: Response,
    practice: Practice,
    platform: PlatformDep,
    gateway: AI,
    player: OptionalPlayer,
    clock: StoryClock,
) -> StoryAttempt:
    response.headers["Cache-Control"] = "no-store"
    return await start_attempt(
        body, practice, platform, gateway, player, client_host(request), clock()
    )


@router.get("/story/attempts/resume")
async def resume_story(
    player: CurrentPlayer, platform: PlatformDep, response: Response
) -> StoryAttempt | None:
    response.headers["Cache-Control"] = "no-store"
    saved = await StoryStore(platform).resume(player.profile.id)
    if saved is None:
        return None
    pin, game = saved
    pack = PACKS[pin.pack_key]
    character = next(cast for cast in pack.cast if cast.id == pin.character_id)
    return story_attempt(
        game, pin, character, chapter_for(pin.pack_key, pin.chapter_id)
    )
