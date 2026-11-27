from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.game.repository import StoryPin
from app.modules.progression import service
from app.modules.progression.models import (
    Season,
    SeasonCharacter,
    SeasonPlayer,
    SeasonStoryProgress,
)

CLEAR_POINTS = 40
CLEAR_COINS = 20
AWAKENING_POINTS = 300


type Requirement = Literal["choose_character", "clear_duel", "earn_points"]


def requirements(selected: bool, cleared: bool, points: int) -> list[Requirement]:
    missing: list[Requirement] = []
    if not selected:
        missing.append("choose_character")
    if not cleared:
        missing.append("clear_duel")
    if points < AWAKENING_POINTS:
        missing.append("earn_points")
    return missing


class StoryProgress(BaseModel):
    cleared: bool
    points: int
    target: int = AWAKENING_POINTS
    awakened_character_id: str | None
    missing: list[Requirement]


class StoryResult(BaseModel):
    escaped: bool
    first_clear: bool
    coins: int
    points: int


async def progress(db: AsyncSession, season_id: UUID, player_id: UUID) -> StoryProgress:
    story = await db.get(SeasonStoryProgress, (season_id, player_id))
    player = await db.get(SeasonPlayer, (season_id, player_id))
    character = await db.get(SeasonCharacter, (season_id, player_id))
    return StoryProgress(
        cleared=story is not None,
        points=player.points if player else 0,
        awakened_character_id=story.awakened_character_id if story else None,
        missing=[]
        if story and story.awakened_character_id
        else requirements(
            character is not None, story is not None, player.points if player else 0
        ),
    )


async def settle(
    db: AsyncSession, pin: StoryPin, player_id: UUID, game_id: UUID, escaped: bool
) -> StoryResult:
    first_clear = False
    if escaped:
        wallet = await service.wallet_lock(db, player_id)
        season = await db.get(Season, pin.season_id)
        if season is None or season.pack_key != pin.pack_key:
            raise AppError(409, "season_unavailable", "This season is unavailable")
        insert_clear = insert(SeasonStoryProgress).values(
            season_id=pin.season_id, player_id=player_id, clear_game_id=game_id
        )
        first_clear_id = await db.scalar(
            insert_clear.on_conflict_do_nothing().returning(
                SeasonStoryProgress.clear_game_id
            )
        )
        if first_clear_id is not None:
            points = insert(SeasonPlayer).values(
                season_id=pin.season_id, player_id=player_id, points=CLEAR_POINTS
            )
            await db.execute(
                points.on_conflict_do_update(
                    index_elements=[SeasonPlayer.season_id, SeasonPlayer.player_id],
                    set_={"points": SeasonPlayer.points + CLEAR_POINTS},
                )
            )
            await service.credit(
                db, wallet, f"story:{pin.season_id}:{player_id}", "story", CLEAR_COINS
            )
            first_clear = True
        else:
            stored = await db.get(SeasonStoryProgress, (pin.season_id, player_id))
            first_clear = stored is not None and stored.clear_game_id == game_id
    return StoryResult(
        escaped=escaped,
        first_clear=first_clear,
        coins=CLEAR_COINS if first_clear else 0,
        points=CLEAR_POINTS if first_clear else 0,
    )


async def awaken(
    db: AsyncSession,
    season_id: UUID,
    player_id: UUID,
    now: datetime,
) -> StoryProgress:
    season = await db.get(Season, season_id)
    if season is None or season.pack_key is None:
        raise AppError(404, "season_not_found", "Season not found")
    await service.wallet_lock(db, player_id)
    story = await db.get(
        SeasonStoryProgress, (season_id, player_id), with_for_update=True
    )
    if story is not None and story.awakened_character_id is not None:
        return await progress(db, season_id, player_id)
    if not season.starts_at <= now < season.ends_at + timedelta(days=3):
        raise AppError(
            409, "claim_window_closed", "The awakening claim window has closed"
        )
    player = await db.get(SeasonPlayer, (season_id, player_id))
    selection = await db.get(
        SeasonCharacter, (season_id, player_id), with_for_update=True
    )
    if requirements(
        selection is not None, story is not None, player.points if player else 0
    ):
        raise AppError(
            409,
            "awakening_locked",
            "Choose a character, clear the duel and earn 300 season points",
        )
    assert story is not None
    assert selection is not None
    story.awakened_character_id = selection.character_id
    await db.flush()
    return await progress(db, season_id, player_id)
