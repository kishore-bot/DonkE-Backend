from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.repository import profiles
from app.modules.social.errors import missing
from app.modules.social.models import (
    Party,
    PartyMember,
)
from app.modules.social.schemas import (
    PartyView,
)


async def members(db: AsyncSession, party_id: UUID) -> list[UUID]:
    return list(
        await db.scalars(
            select(PartyMember.player_id)
            .where(PartyMember.party_id == party_id)
            .order_by(PartyMember.player_id)
        )
    )


async def party_for(db: AsyncSession, player: UUID, *, lock: bool = False) -> Party:
    query = select(Party).join(PartyMember).where(PartyMember.player_id == player)
    if lock:
        query = query.with_for_update(of=Party)
    party = await db.scalar(query)
    if party is None:
        raise missing("party_not_found")
    return party


async def party_view(db: AsyncSession, party: Party) -> PartyView:
    names = await profiles(db, await members(db, party.id))
    return PartyView(
        id=party.id, leader_id=party.leader_id, members=list(names.values())
    )
