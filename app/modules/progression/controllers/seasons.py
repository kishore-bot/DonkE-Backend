from uuid import UUID

from fastapi import APIRouter, Response

from app.core.dependencies import OptionalPlatform, PlatformDep
from app.modules.identity.dependencies import CurrentPlayer, PlayerWrites
from app.modules.progression.dependencies import SeasonProgress
from app.modules.progression.helpers.clock import utc_now
from app.modules.progression.schemas import squads
from app.modules.progression.schemas.content import (
    CharacterSelection,
    SeasonManifest,
    SelectCharacter,
)
from app.modules.progression.schemas.emotes import EmoteSelection, SeasonEmotes
from app.modules.progression.schemas.seasons import MySeason, Standing
from app.modules.progression.services import seasons
from app.modules.progression.services import squads as squads_service
from app.modules.progression.services.emotes import season_emotes

router = APIRouter()


@router.get("/seasons/current")
async def current(player: CurrentPlayer, progress: SeasonProgress) -> MySeason | None:
    return await progress.current(player.profile.id)


@router.get("/seasons/squads")
async def season_squads(
    player: CurrentPlayer, platform: PlatformDep, response: Response
) -> squads.SquadOverview:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions() as db:
        return await squads_service.overview(db, player.profile.id, utc_now())


@router.post("/seasons/{season_id}/squad", dependencies=PlayerWrites)
async def enroll_squad(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> squads.SquadProgress:
    async with platform.sessions.begin() as db:
        return await squads_service.enroll(db, season_id, player.profile.id, utc_now())


@router.post("/seasons/{season_id}/squad/claim", dependencies=PlayerWrites)
async def claim_squad(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> squads.SquadProgress:
    async with platform.sessions.begin() as db:
        return await squads_service.claim(db, season_id, player.profile.id, utc_now())


@router.get("/seasons/active/manifest")
async def season_manifest(
    platform: OptionalPlatform, response: Response
) -> SeasonManifest | None:
    """The published cast and schedule for guests and signed-in players."""
    response.headers["Cache-Control"] = "no-store"
    if platform is None:
        return None
    async with platform.sessions() as db:
        return await seasons.active_manifest(db, utc_now())


@router.get("/seasons/{season_id}/me/character")
async def selected_character(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep, response: Response
) -> CharacterSelection:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions() as db:
        return await seasons.season_character(
            db, season_id, player.profile.id, utc_now()
        )


@router.put("/seasons/{season_id}/me/character", dependencies=PlayerWrites)
async def choose_character(
    season_id: UUID, body: SelectCharacter, player: CurrentPlayer, platform: PlatformDep
) -> CharacterSelection:
    async with platform.sessions.begin() as db:
        return await seasons.season_character(
            db,
            season_id,
            player.profile.id,
            utc_now(),
            character_id=body.character_id,
        )


@router.get("/seasons/{season_id}/me/emote")
async def selected_emote(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep, response: Response
) -> SeasonEmotes:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions() as db:
        return await season_emotes(db, season_id, player.profile.id, utc_now())


@router.put("/seasons/{season_id}/me/emote", dependencies=PlayerWrites)
async def choose_emote(
    season_id: UUID,
    body: EmoteSelection,
    player: CurrentPlayer,
    platform: PlatformDep,
    response: Response,
) -> SeasonEmotes:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions.begin() as db:
        return await season_emotes(db, season_id, player.profile.id, utc_now(), body)


@router.get("/seasons/{season_id}/board")
async def board(
    season_id: UUID, _: CurrentPlayer, progress: SeasonProgress
) -> list[Standing]:
    return await progress.board(season_id)
