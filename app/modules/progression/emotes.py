"""Account-owned emote loadouts scoped to a packed season."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.game.schemas import SceneEmote
from app.modules.progression.catalog import CATALOG
from app.modules.progression.models import Cosmetic, SeasonEmote
from app.modules.progression.services.seasons import active_manifest


class EmoteSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str | None = Field(min_length=1, max_length=80)


class SeasonEmotes(BaseModel):
    selected: SceneEmote
    options: list[SceneEmote]


def choices(season_id: UUID) -> dict[str, SceneEmote]:
    fan = "grimoire_fan:emote"
    salute = "duelist_salute:emote"
    tier = f"tier:{season_id}:25:emote"
    bonus = f"bonus:{season_id}:1:emote"
    return {
        fan: SceneEmote(sku=fan, title=CATALOG[fan].label, motion="flourish"),
        salute: SceneEmote(sku=salute, title=CATALOG[salute].label, motion="salute"),
        tier: SceneEmote(sku=tier, title="Season tier emote", motion="flourish"),
        bonus: SceneEmote(sku=bonus, title="Streak bonus emote", motion="salute"),
    }


async def pinned_emote(
    db: AsyncSession, season_id: UUID, player_id: UUID
) -> SceneEmote:
    setting = await db.get(SeasonEmote, (season_id, player_id))
    return (
        choices(season_id).get(setting.sku, SceneEmote()) if setting else SceneEmote()
    )


async def season_emotes(
    db: AsyncSession,
    season_id: UUID,
    player_id: UUID,
    now: datetime,
    selection: EmoteSelection | None = None,
) -> SeasonEmotes:
    manifest = await active_manifest(db, now)
    if manifest is None or manifest.season_id != season_id:
        raise AppError(409, "season_unavailable", "This season is unavailable")
    available = choices(season_id)
    owned = await db.scalars(
        select(Cosmetic.sku).where(
            Cosmetic.player_id == player_id, Cosmetic.sku.in_(available)
        )
    )
    standard = SceneEmote()
    by_sku = {sku: available[sku] for sku in owned}
    options = [standard, *(entry for sku, entry in available.items() if sku in by_sku)]
    if selection is None:
        saved = await db.get(SeasonEmote, (season_id, player_id))
        return SeasonEmotes(
            selected=by_sku.get(saved.sku, standard) if saved else standard,
            options=options,
        )

    if selection.sku is None:
        await db.execute(
            delete(SeasonEmote).where(
                SeasonEmote.season_id == season_id, SeasonEmote.player_id == player_id
            )
        )
        return SeasonEmotes(selected=standard, options=options)
    emote = by_sku.get(selection.sku)
    if emote is None:
        raise AppError(
            404, "emote_unavailable", "Choose an emote you own for this season"
        )
    row = insert(SeasonEmote).values(
        season_id=season_id, player_id=player_id, sku=selection.sku
    )
    await db.execute(
        row.on_conflict_do_update(
            index_elements=[SeasonEmote.season_id, SeasonEmote.player_id],
            set_={"sku": row.excluded.sku},
        )
    )
    return SeasonEmotes(selected=emote, options=options)
