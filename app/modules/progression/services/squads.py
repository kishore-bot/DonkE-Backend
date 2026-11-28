from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.identity.repositories.players import profiles
from app.modules.progression.helpers.calendar import (
    CLAIM_GRACE,
    claim_deadline,
    window_open,
)
from app.modules.progression.helpers.squads import GIFT_COINS
from app.modules.progression.models.coin_ledger import CoinLedger
from app.modules.progression.models.season import Season
from app.modules.progression.models.season_squad import SeasonSquad
from app.modules.progression.models.season_squad_member import SeasonSquadMember
from app.modules.progression.repositories.economy import credit, own, wallet_lock
from app.modules.progression.schemas.squads import SquadOverview, SquadProgress
from app.modules.progression.services.seasons import active_season, lock_season_schedule
from app.modules.social.repositories.parties import members, party_for


def reference(season_id: UUID, player: UUID) -> str:
    return f"squad:{season_id}:{player}"


async def view(
    db: AsyncSession, season: Season, member: SeasonSquadMember, now: datetime
) -> SquadProgress:
    roster = await db.get(SeasonSquad, (season.id, member.party_id))
    assert roster is not None
    completed = (
        await db.scalar(
            select(func.count(SeasonSquadMember.clear_game_id)).where(
                SeasonSquadMember.season_id == season.id,
                SeasonSquadMember.party_id == member.party_id,
            )
        )
        or 0
    )
    claimed = (
        await db.get(CoinLedger, reference(season.id, member.player_id)) is not None
    )
    return SquadProgress(
        season_id=season.id,
        title=season.theme,
        completed=completed,
        target=roster.target,
        contributed=member.clear_game_id is not None,
        claim_deadline=claim_deadline(season.ends_at),
        can_claim=not claimed
        and completed == roster.target
        and window_open(season.starts_at, season.ends_at, now),
        claimed=claimed,
    )


async def overview(db: AsyncSession, player: UUID, now: datetime) -> SquadOverview:
    active = await active_season(db, now)
    rows = await db.execute(
        select(Season, SeasonSquadMember)
        .join(SeasonSquadMember, SeasonSquadMember.season_id == Season.id)
        .where(
            SeasonSquadMember.player_id == player,
            Season.starts_at <= now,
            Season.ends_at > now - CLAIM_GRACE,
        )
        .order_by(Season.ends_at)
    )
    return SquadOverview(
        active_season_id=active.id if active and active.pack_key is not None else None,
        squads=[await view(db, season, member, now) for season, member in rows],
    )


async def enroll(
    db: AsyncSession, season_id: UUID, player: UUID, now: datetime
) -> SquadProgress:
    await lock_season_schedule(db, read=True)
    season = await active_season(db, now)
    if season is None or season.id != season_id or season.pack_key is None:
        raise AppError(409, "season_unavailable", "This season is unavailable")
    party = await party_for(db, player, lock=True)
    if party.leader_id != player:
        raise AppError(
            403, "leader_required", "Only the party leader can enroll the squad"
        )
    roster = await db.get(SeasonSquad, (season_id, party.id))
    if roster is not None:
        member = await db.get(SeasonSquadMember, (season_id, player))
        if member is None or member.party_id != party.id:
            raise AppError(
                409, "squad_roster_locked", "This season's roster is already fixed"
            )
        return await view(db, season, member, now)
    players = await profiles(db, await members(db, party.id))
    if not 2 <= len(players) <= 4:
        raise AppError(
            409, "squad_size", "Enroll with two to four active party members"
        )
    db.add(SeasonSquad(season_id=season_id, party_id=party.id, target=len(players)))
    await db.flush()
    inserted = await db.scalars(
        insert(SeasonSquadMember)
        .values(
            [
                {"season_id": season_id, "party_id": party.id, "player_id": member_id}
                for member_id in players
            ]
        )
        .on_conflict_do_nothing()
        .returning(SeasonSquadMember.player_id)
    )
    if len(inserted.all()) != len(players):
        raise AppError(
            409, "squad_already_enrolled", "A member already joined a squad this season"
        )
    member = await db.get(SeasonSquadMember, (season_id, player))
    assert member is not None
    return await view(db, season, member, now)


async def contribute(
    db: AsyncSession,
    season: Season,
    party: UUID,
    player: UUID,
    game: UUID,
    now: datetime,
) -> None:
    if window_open(season.starts_at, season.ends_at, now):
        await db.execute(
            update(SeasonSquadMember)
            .where(
                SeasonSquadMember.season_id == season.id,
                SeasonSquadMember.party_id == party,
                SeasonSquadMember.player_id == player,
                SeasonSquadMember.clear_game_id.is_(None),
            )
            .values(clear_game_id=game)
        )


async def claim(
    db: AsyncSession, season_id: UUID, player: UUID, now: datetime
) -> SquadProgress:
    wallet = await wallet_lock(db, player)
    member = await db.get(SeasonSquadMember, (season_id, player))
    season = await db.get(Season, season_id)
    if member is None or season is None:
        raise AppError(404, "squad_not_found", "Season squad not found")
    result = await view(db, season, member, now)
    if result.claimed:
        return result
    if not window_open(season.starts_at, season.ends_at, now):
        raise AppError(409, "claim_window_closed", "The squad claim window has closed")
    if not result.can_claim:
        raise AppError(
            409, "squad_gift_locked", "Complete all squad clears to claim this gift"
        )
    await credit(db, wallet, reference(season_id, player), "squad", GIFT_COINS)
    await own(db, player, f"squad:{season_id}:frame")
    return result.model_copy(update={"claimed": True, "can_claim": False})
