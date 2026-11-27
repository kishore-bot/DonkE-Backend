from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.rate_limit import client_host
from app.modules.game.repository import StoryPin
from app.modules.game.router import Service
from app.modules.game.schemas import PracticeCreated
from app.modules.identity.router import (
    CurrentPlayer,
    PlatformDep,
    bearer,
    current_player,
)
from app.modules.lobby.router import Writes
from app.modules.progression.models import SeasonCharacter
from app.modules.progression.season_content import CharacterPreview
from app.modules.progression.service import active_manifest
from app.modules.story.progression import (
    StoryProgress,
    StoryResult,
    awaken,
    progress,
    settle,
)

router = APIRouter(prefix="/api/v1", tags=["Story"])
AUTHORED_DUELS = {
    "grimoire-awakening-v1": (5, "The Arena Keeper"),
    "skybound-voyage-v1": (41, "The Storm Captain"),
}


class StartDuel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    season_id: UUID
    character_id: str | None = Field(default=None, min_length=1, max_length=40)


class StoryAttempt(PracticeCreated):
    rival: str
    character: CharacterPreview
    rewards_eligible: bool


class ResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_token: str = Field(min_length=1, max_length=128, repr=False)


@router.post("/story/attempts", status_code=201)
async def start_duel(
    body: StartDuel,
    request: Request,
    response: Response,
    practice: Service,
    platform: PlatformDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> StoryAttempt:
    player = await current_player(platform, credentials) if credentials else None
    player_id = player.profile.id if player else None
    async with platform.sessions() as db:
        manifest = await active_manifest(db, datetime.now(UTC))
        if manifest is None or manifest.season_id != body.season_id:
            raise AppError(409, "season_unavailable", "This season is unavailable")
        selection = (
            await db.get(SeasonCharacter, (body.season_id, player_id))
            if player_id
            else None
        )
        cast = {character.id: character for character in manifest.pack.cast}
        character_id = (
            selection.character_id
            if selection
            else body.character_id or next(iter(cast))
        )
        if character_id not in cast:
            raise AppError(
                404,
                "season_character_not_found",
                "Character is unavailable in this season",
            )
        pin = StoryPin(manifest.season_id, manifest.pack_key, character_id, player_id)
    duel = AUTHORED_DUELS.get(pin.pack_key)
    if duel is None:
        raise AppError(404, "story_unavailable", "This season has no story duel")
    seed, rival = duel
    game = await run_in_threadpool(
        practice.create, 2, client=client_host(request), story=pin, seed=seed
    )
    response.headers["Cache-Control"] = "no-store"
    return StoryAttempt(
        **game.model_dump(),
        rival=rival,
        character=cast[character_id],
        rewards_eligible=player_id is not None,
    )


@router.post("/story/attempts/{game_id}/result", dependencies=Writes)
async def story_result(
    game_id: UUID,
    body: ResultRequest,
    player: CurrentPlayer,
    platform: PlatformDep,
    practice: Service,
) -> StoryResult:
    player_id = player.profile.id
    pin, escaped = await run_in_threadpool(
        practice.story_result, game_id, body.attempt_token, player_id
    )
    async with platform.sessions.begin() as db:
        return await settle(db, pin, player_id, game_id, escaped)


@router.get("/seasons/{season_id}/me/story")
async def get_progress(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> StoryProgress:
    async with platform.sessions() as db:
        return await progress(db, season_id, player.profile.id)


@router.post("/seasons/{season_id}/me/awakening", dependencies=Writes)
async def claim_awakening(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> StoryProgress:
    async with platform.sessions.begin() as db:
        return await awaken(db, season_id, player.profile.id, datetime.now(UTC))
