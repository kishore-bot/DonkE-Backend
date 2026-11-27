import asyncio
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.platform import Platform
from app.core.rate_limit import limit
from app.modules.ai.gateway import Gateway
from app.modules.game.rival_memory import recall
from app.modules.game.schemas import PracticeCreated, SceneEmote, StoryEvent
from app.modules.game.seeded import SeededDuel
from app.modules.game.service import PracticeService
from app.modules.game.story_state import StoryPin
from app.modules.game.story_store import StoryStore, for_attempt
from app.modules.identity.service import Principal
from app.modules.progression.emotes import pinned_emote
from app.modules.progression.models import SeasonCharacter, SeasonSquadMember
from app.modules.progression.season_content import CharacterPreview
from app.modules.progression.services.seasons import active_manifest
from app.modules.story.chapters import (
    Chapter,
    chapter_for,
    cleared_chapters,
    describe,
)
from app.modules.story.rival import expert_search, rival_budget
from app.modules.story.schemas import StartDuel, StoryAttempt


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
        emote=pin.emote,
        rival_memory=pin.remembered,
        rival_target_rating=pin.target_rating,
        rival_intent=pin.intent,
    )


def public_memory(moment: StoryEvent | None) -> str:
    if moment is None:
        return "no earlier public result"
    return f"{moment.kind}, move {moment.move}, seat {moment.seat}, recipient {moment.recipient}, led suit {moment.led_suit}"


async def finished_duel(
    practice: PracticeService,
    platform: Platform,
    game_id: UUID,
    token: str,
) -> tuple[StoryPin, SeededDuel]:
    store = for_attempt(platform, game_id, token)
    if store is not None:
        return await store.finished(game_id, token)
    return await run_in_threadpool(practice.story_decision, game_id, token)


async def start_attempt(
    body: StartDuel,
    practice: PracticeService,
    platform: Platform,
    gateway: Gateway,
    player: Principal | None,
    client: str,
    now: datetime,
) -> StoryAttempt:
    player_id = player.profile.id if player else None
    async with platform.sessions() as db:
        manifest = await active_manifest(db, now)
        if manifest is None or manifest.season_id != body.season_id:
            raise AppError(409, "season_unavailable", "This season is unavailable")
        chapter = chapter_for(manifest.pack_key, body.chapter_id)
        route = body.route or next(iter(manifest.pack.routes), None)
        if route is not None and route not in manifest.pack.routes:
            raise AppError(
                422, "story_route_unavailable", "Choose a route for this season"
            )
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
            emote=await pinned_emote(db, manifest.season_id, player_id)
            if player_id
            else SceneEmote(),
            route=route,
        )
        if body.adaptive and player is not None:
            memory = await recall(db, manifest.season_id, player.profile.id, chapter.id)
            budget, target = rival_budget(player.profile.mmr)
            pin = replace(
                pin,
                remembered=memory,
                target_rating=target,
                rival_budget=budget,
                rival_expert=expert_search(player.profile.mmr),
                rival_avoid_suit=memory.led_suit
                if memory and memory.seat == 0
                else None,
            )
    if player_id is not None:
        await limit(
            platform,
            "story_start",
            client,
            platform.settings.practice_creates_per_minute,
            60,
        )
    if body.adaptive:
        intent = "pressure" if pin.remembered and pin.remembered.seat == 0 else "steady"
        pin = replace(pin, intent=intent)
    if body.adaptive and gateway.provider is not None:
        await limit(platform, "story_rival", client, 4, 60)
        try:
            async with asyncio.timeout(1.25):
                intent = await gateway.select(
                    "story_rival",
                    f"Choose steady or pressure for {chapter.rival} in the {manifest.pack.title} card duel. "
                    f"Last public moment: {public_memory(pin.remembered)}.",
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
            client=client,
            story=pin,
            seed=chapter.seed,
        )
    return story_attempt(game, pin, cast[character_id], chapter)
