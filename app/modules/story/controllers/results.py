from uuid import UUID

from fastapi import APIRouter, Response

from app.core.dependencies import PlatformDep
from app.core.errors import AppError
from app.modules.game.helpers.seeded_duel import SeededDuel
from app.modules.game.services.story_store import PIN, StoryStore
from app.modules.identity.dependencies import (
    CurrentPlayer,
    PlayerWrites,
)
from app.modules.story.dependencies import StoryClock
from app.modules.story.schemas.duel import ResultRequest
from app.modules.story.schemas.progression import (
    AwakeningPath,
    PendingAwakening,
    StoryProgress,
    StoryResult,
)
from app.modules.story.services.progression import (
    awakening_path,
    pending_awakening,
    progress,
)
from app.modules.story.services.settlement import awaken, settle

router = APIRouter()


@router.post("/story/attempts/{game_id}/result", dependencies=PlayerWrites)
async def story_result(
    game_id: UUID,
    body: ResultRequest,
    player: CurrentPlayer,
    platform: PlatformDep,
    response: Response,
    clock: StoryClock,
) -> StoryResult:
    player_id = player.profile.id
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions.begin() as db:
        row = await StoryStore(platform).load(
            db, game_id, body.attempt_token, lock=True, player=player_id
        )
        if row.receipt is not None:
            return StoryResult.model_validate(row.receipt)
        if not row.finished:
            raise AppError(409, "story_in_progress", "Finish the story duel first")
        pin = PIN.validate_python(row.pin)
        duel = SeededDuel.restore(row.duel)
        escaped = 0 in duel.player_view()["escape_order"]
        objective = duel.objective() if duel.route else None
        receipt = await settle(db, pin, player_id, game_id, escaped, clock(), objective)
        row.receipt = receipt.model_dump(mode="json")
        return receipt


@router.get("/seasons/{season_id}/me/story")
async def get_progress(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> StoryProgress:
    async with platform.sessions() as db:
        return await progress(db, season_id, player.profile.id)


@router.get("/seasons/{season_id}/me/awakening/path")
async def explain_awakening(
    season_id: UUID,
    player: CurrentPlayer,
    platform: PlatformDep,
    response: Response,
    clock: StoryClock,
) -> AwakeningPath:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions() as db:
        return await awakening_path(db, season_id, player.profile.id, clock())


@router.get("/story/awakening/pending")
async def pending_final_form(
    player: CurrentPlayer,
    platform: PlatformDep,
    response: Response,
    clock: StoryClock,
) -> PendingAwakening | None:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions() as db:
        return await pending_awakening(db, player.profile.id, clock())


@router.post("/seasons/{season_id}/me/awakening", dependencies=PlayerWrites)
async def claim_awakening(
    season_id: UUID,
    player: CurrentPlayer,
    platform: PlatformDep,
    clock: StoryClock,
) -> StoryProgress:
    async with platform.sessions.begin() as db:
        return await awaken(db, season_id, player.profile.id, clock())
