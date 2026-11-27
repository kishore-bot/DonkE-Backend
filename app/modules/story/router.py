import asyncio
from datetime import UTC, datetime
from dataclasses import replace
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.rate_limit import client_host, limit
from app.modules.ai.index import ranked_rules
from app.modules.ai.router import AI
from app.modules.game.repository import StoryPin
from app.modules.game.router import AccessToken, Service
from app.modules.game.schemas import PracticeCreated
from app.modules.game.seeded import SeededDuel
from app.modules.game.story_store import PIN, StoryStore, for_attempt
from app.modules.identity.router import (
    CurrentPlayer,
    PlatformDep,
    bearer,
    current_player,
)
from app.modules.lobby.router import Writes
from app.modules.progression.models import SeasonCharacter, SeasonSquadMember
from app.modules.progression.season_content import PACKS, CharacterPreview
from app.modules.progression.service import active_manifest
from app.modules.story.challenge import (
    ChallengeLink,
    ChallengeView,
    challenge_character,
    challenge_link,
    read_challenge,
)
from app.modules.story.chapters import (
    CHAPTERS,
    OPENING_CHAPTER,
    Chapter,
    ChapterView,
    chapter_for,
    cleared_chapters,
    describe,
)
from app.modules.story.coach import DuelCoach, explain
from app.modules.story.progression import (
    AwakeningPath,
    PendingAwakening,
    StoryProgress,
    StoryResult,
    awaken,
    awakening_path,
    pending_awakening,
    progress,
    settle,
)

router = APIRouter(prefix="/api/v1", tags=["Story"])


class StartDuel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    season_id: UUID
    chapter_id: str = Field(default=OPENING_CHAPTER, min_length=1, max_length=40)
    adaptive: bool = False
    character_id: str | None = Field(default=None, min_length=1, max_length=40)


class StoryAttempt(PracticeCreated):
    season_id: UUID
    pack_key: str
    chapter_id: str
    chapter_title: str
    rival: str
    character: CharacterPreview
    rewards_eligible: bool


ChallengeCode = Annotated[
    str, Path(min_length=48, max_length=768, pattern=r"^[A-Za-z0-9_.-]+$")
]


class ResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_token: str = Field(min_length=1, max_length=128, repr=False)


def story_attempt(
    game: PracticeCreated,
    pin: StoryPin,
    character: CharacterPreview,
    chapter: Chapter,
) -> StoryAttempt:
    return StoryAttempt(
        **game.model_dump(),
        season_id=pin.season_id,
        pack_key=pin.pack_key,
        chapter_id=chapter.id,
        chapter_title=chapter.title,
        rival=chapter.rival,
        character=character,
        rewards_eligible=pin.player_id is not None,
    )


@router.get("/seasons/{season_id}/story/chapters")
async def campaign(
    season_id: UUID,
    platform: PlatformDep,
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> list[ChapterView]:
    player = await current_player(platform, credentials) if credentials else None
    player_id = player.profile.id if player else None
    now = datetime.now(UTC)
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
    practice: Service,
    platform: PlatformDep,
    gateway: AI,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> StoryAttempt:
    player = await current_player(platform, credentials) if credentials else None
    player_id = player.profile.id if player else None
    now = datetime.now(UTC)
    async with platform.sessions() as db:
        manifest = await active_manifest(db, now)
        if manifest is None or manifest.season_id != body.season_id:
            raise AppError(409, "season_unavailable", "This season is unavailable")
        chapter = chapter_for(manifest.pack_key, body.chapter_id)
        if chapter.requires is not None:
            cleared = await cleared_chapters(db, manifest.season_id, player_id)
            status = describe(manifest, chapter, player_id, cleared, now).status
            if status not in {"ready", "cleared"}:
                raise AppError(
                    409, "chapter_locked", "Unlock this chapter on the story map"
                )
        selection = (
            await db.get(SeasonCharacter, (body.season_id, player_id))
            if player_id
            else None
        )
        squad_member = (
            await db.get(SeasonSquadMember, (body.season_id, player_id))
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
        pin = StoryPin(
            manifest.season_id,
            manifest.pack_key,
            character_id,
            player_id,
            squad_party_id=squad_member.party_id if squad_member else None,
            chapter_id=chapter.id,
        )
    if player_id is not None:
        await limit(
            platform,
            "story_start",
            client_host(request),
            platform.settings.practice_creates_per_minute,
            60,
        )
    if body.adaptive and gateway.provider is not None:
        await limit(platform, "story_rival", client_host(request), 4, 60)
        try:
            async with asyncio.timeout(1.25):
                intent = await gateway.select(
                    "story_rival",
                    f"Choose steady or pressure for {chapter.rival} in the {manifest.pack.title} card duel.",
                    {"steady", "pressure"},
                )
        except TimeoutError, RedisError:
            intent = None
        if intent == "pressure":
            pin = replace(pin, intent="pressure", intent_source="gemini")
        elif intent == "steady":
            pin = replace(pin, intent_source="gemini")
    if player_id is not None:
        game = await StoryStore(platform).create(pin, chapter.seed)
    else:
        game = await run_in_threadpool(
            practice.create,
            2,
            client=client_host(request),
            story=pin,
            seed=chapter.seed,
        )
    response.headers["Cache-Control"] = "no-store"
    return story_attempt(game, pin, cast[character_id], chapter)


async def finished_duel(
    practice: Service,
    platform: PlatformDep,
    game_id: UUID,
    token: AccessToken,
) -> tuple[StoryPin, SeededDuel]:
    store = for_attempt(platform, game_id, token)
    if store is not None:
        return await store.finished(game_id, token)
    return await run_in_threadpool(practice.story_decision, game_id, token)


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


@router.post("/story/attempts/{game_id}/share")
async def share_attempt(
    game_id: UUID,
    token: AccessToken,
    practice: Service,
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
    practice: Service,
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


@router.post("/story/attempts/{game_id}/result", dependencies=Writes)
async def story_result(
    game_id: UUID,
    body: ResultRequest,
    player: CurrentPlayer,
    platform: PlatformDep,
    response: Response,
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
        escaped = 0 in SeededDuel.restore(row.duel).player_view()["escape_order"]
        receipt = await settle(db, pin, player_id, game_id, escaped, datetime.now(UTC))
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
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep, response: Response
) -> AwakeningPath:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions() as db:
        return await awakening_path(db, season_id, player.profile.id, datetime.now(UTC))


@router.get("/story/awakening/pending")
async def pending_final_form(
    player: CurrentPlayer, platform: PlatformDep, response: Response
) -> PendingAwakening | None:
    response.headers["Cache-Control"] = "no-store"
    async with platform.sessions() as db:
        return await pending_awakening(db, player.profile.id, datetime.now(UTC))


@router.post("/seasons/{season_id}/me/awakening", dependencies=Writes)
async def claim_awakening(
    season_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> StoryProgress:
    async with platform.sessions.begin() as db:
        return await awaken(db, season_id, player.profile.id, datetime.now(UTC))


@router.get("/story/attempts/{game_id}/coach")
async def story_coach(
    game_id: UUID,
    request: Request,
    response: Response,
    token: AccessToken,
    practice: Service,
    gateway: AI,
    question: Annotated[str | None, Query(min_length=2, max_length=240)] = None,
) -> DuelCoach:
    await limit(gateway.platform, "story_coach", client_host(request), 15, 60)
    pin, duel = await finished_duel(practice, gateway.platform, game_id, token)
    response.headers["Cache-Control"] = "no-store"
    if question is None:
        return await run_in_threadpool(explain, pin, duel)
    rules = await ranked_rules(gateway, question)
    if not rules:
        return DuelCoach(
            answer="I could not find evidence for that question in the game rules."
        )
    rule = rules[0]
    return DuelCoach(answer=rule.en, citation=f"rule:{rule.source}")
