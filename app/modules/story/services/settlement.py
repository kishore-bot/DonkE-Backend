from datetime import datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.game.dto.story_pin import StoryPin
from app.modules.game.schemas.story import StoryObjective
from app.modules.progression.helpers.calendar import window_open
from app.modules.progression.models.season import Season
from app.modules.progression.models.season_chapter_clear import SeasonChapterClear
from app.modules.progression.models.season_character import SeasonCharacter
from app.modules.progression.models.season_player import SeasonPlayer
from app.modules.progression.models.season_story_progress import SeasonStoryProgress
from app.modules.progression.repositories.economy import credit, wallet_lock
from app.modules.progression.services import squads
from app.modules.progression.services.seasons import lock_season_schedule
from app.modules.story.helpers.awakening import requirements
from app.modules.story.helpers.chapters import OPENING_CHAPTER, chapter_for
from app.modules.story.schemas.progression import StoryProgress, StoryResult
from app.modules.story.services.progression import progress


async def settle(
    db: AsyncSession,
    pin: StoryPin,
    player_id: UUID,
    game_id: UUID,
    escaped: bool,
    now: datetime,
    objective: StoryObjective | None = None,
) -> StoryResult:
    chapter = chapter_for(pin.pack_key, pin.chapter_id)
    first_clear = False
    if escaped and (objective is None or objective.met):
        await lock_season_schedule(db, read=True)
        wallet = await wallet_lock(db, player_id)
        season = await db.get(Season, pin.season_id)
        if season is None or season.pack_key != pin.pack_key:
            raise AppError(409, "season_unavailable", "This season is unavailable")
        row_key = (pin.season_id, player_id)
        suffix = "" if chapter.id == OPENING_CHAPTER else f":{chapter.id}"
        if chapter.id == OPENING_CHAPTER:
            inserted = await db.scalar(
                insert(SeasonStoryProgress)
                .values(
                    season_id=pin.season_id, player_id=player_id, clear_game_id=game_id
                )
                .on_conflict_do_nothing()
                .returning(SeasonStoryProgress.clear_game_id)
            )
            stored = (
                await db.get(SeasonStoryProgress, row_key) if inserted is None else None
            )
            first_clear = inserted is not None or (
                stored is not None and stored.clear_game_id == game_id
            )
        else:
            inserted = await db.scalar(
                insert(SeasonChapterClear)
                .values(
                    season_id=pin.season_id,
                    player_id=player_id,
                    chapter_id=chapter.id,
                    game_id=game_id,
                )
                .on_conflict_do_nothing()
                .returning(SeasonChapterClear.game_id)
            )
            old = (
                await db.get(SeasonChapterClear, (*row_key, chapter.id))
                if inserted is None
                else None
            )
            first_clear = inserted is not None or (
                old is not None and old.game_id == game_id
            )
        if inserted is not None:
            points = insert(SeasonPlayer).values(
                season_id=pin.season_id, player_id=player_id, points=chapter.points
            )
            await db.execute(
                points.on_conflict_do_update(
                    index_elements=[SeasonPlayer.season_id, SeasonPlayer.player_id],
                    set_={"points": SeasonPlayer.points + chapter.points},
                )
            )
            await credit(
                db,
                wallet,
                f"story:{pin.season_id}:{player_id}{suffix}",
                "story",
                chapter.coins,
            )
        if pin.squad_party_id is not None:
            await squads.contribute(
                db, season, pin.squad_party_id, player_id, game_id, now
            )
    return StoryResult(
        escaped=escaped,
        first_clear=first_clear,
        coins=chapter.coins if first_clear else 0,
        points=chapter.points if first_clear else 0,
        objective=objective,
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
    await wallet_lock(db, player_id)
    story = await db.get(
        SeasonStoryProgress, (season_id, player_id), with_for_update=True
    )
    if story is not None and story.awakened_character_id is not None:
        return await progress(db, season_id, player_id)
    if not window_open(season.starts_at, season.ends_at, now):
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
