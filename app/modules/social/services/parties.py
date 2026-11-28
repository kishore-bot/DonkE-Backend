from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.identity.repositories.players import profiles
from app.modules.lobby.schemas.queue import QueueStatus
from app.modules.lobby.services.lobby import LobbyService
from app.modules.social.helpers.errors import conflict, missing
from app.modules.social.helpers.moderation import pair
from app.modules.social.models.friendship import Friendship
from app.modules.social.models.party import Party
from app.modules.social.models.party_invite import PartyInvite
from app.modules.social.models.party_member import PartyMember
from app.modules.social.repositories.parties import members, party_for, party_view
from app.modules.social.repositories.safety import ensure_not_blocked
from app.modules.social.schemas.parties import PartyView


class PartyService:
    def __init__(self, platform: Platform, lobby: LobbyService):
        self.platform = platform
        self.lobby = lobby

    async def create_party(self, player_id: UUID) -> PartyView:
        try:
            async with self.platform.sessions() as db:
                return await party_view(db, await party_for(db, player_id))
        except AppError as exc:
            if exc.code != "party_not_found":
                raise
        async with self.platform.sessions.begin() as db:
            party = Party(leader_id=player_id)
            db.add(party)
            await db.flush()
            query = insert(PartyMember).values(player_id=player_id, party_id=party.id)
            joined = await db.scalar(
                query.on_conflict_do_nothing().returning(PartyMember.player_id)
            )
            if joined is None:
                raise conflict("party_busy", "Player already belongs to a party")
            return await party_view(db, party)

    async def my_party(self, player_id: UUID) -> PartyView:
        async with self.platform.sessions() as db:
            return await party_view(db, await party_for(db, player_id))

    async def invites(self, player_id: UUID) -> list[UUID]:
        async with self.platform.sessions() as db:
            return list(
                await db.scalars(
                    select(PartyInvite.party_id).where(
                        PartyInvite.player_id == player_id
                    )
                )
            )

    async def invite(self, player_id: UUID, other: UUID) -> None:
        async with self.platform.sessions.begin() as db:
            party = await party_for(db, player_id, lock=True)
            if party.leader_id != player_id:
                raise AppError(
                    403, "leader_required", "Only the party leader can invite"
                )
            edge = await db.get(Friendship, pair(player_id, other))
            if edge is None or not edge.accepted:
                raise AppError(403, "friend_required", "Invite an accepted friend")
            await ensure_not_blocked(db, player_id, other)
            await db.execute(
                insert(PartyInvite)
                .values(party_id=party.id, player_id=other)
                .on_conflict_do_nothing()
            )

    async def accept_invite(self, player_id: UUID, party_id: UUID) -> PartyView:
        async with self.platform.sessions.begin() as db:
            party = await db.get(Party, party_id, with_for_update=True)
            if party is None:
                raise missing("party_not_found")
            roster = await members(db, party_id)
            if player_id in roster:
                return await party_view(db, party)
            invite = await db.get(PartyInvite, (party_id, player_id))
            if invite is None:
                raise missing("invite_not_found")
            if len(roster) >= 4:
                raise conflict("party_full", "The party has four players")
            active = await profiles(db, [party.leader_id, player_id])
            leader, invitee = active.get(party.leader_id), active.get(player_id)
            if (
                leader is None
                or (await self.lobby.queue_status(leader)).status != "idle"
            ):
                raise conflict(
                    "party_busy", "Leave the queue or room before changing your party"
                )
            if (
                invitee is None
                or (await self.lobby.queue_status(invitee)).status != "idle"
            ):
                raise conflict(
                    "player_busy", "Leave the queue or room before joining a party"
                )
            result = await db.scalar(
                insert(PartyMember)
                .values(player_id=player_id, party_id=party_id)
                .on_conflict_do_nothing()
                .returning(PartyMember.player_id)
            )
            if result is None:
                raise conflict("party_busy", "Player already belongs to a party")
            await db.delete(invite)
            return await party_view(db, party)

    async def leave(self, player_id: UUID) -> None:
        async with self.platform.sessions.begin() as db:
            party = await party_for(db, player_id, lock=True)
            leader = (await profiles(db, [party.leader_id])).get(party.leader_id)
            if (
                leader is not None
                and (await self.lobby.queue_status(leader)).status != "idle"
            ):
                raise conflict(
                    "party_busy", "Leave the queue or room before changing your party"
                )
            membership = await db.get(PartyMember, player_id)
            if membership is None:
                return
            remaining = [
                member for member in await members(db, party.id) if member != player_id
            ]
            if not remaining:
                await db.delete(party)
            else:
                await db.delete(membership)
                if party.leader_id == player_id:
                    party.leader_id = remaining[0]

    async def queue(self, player_id: UUID) -> QueueStatus:
        async with self.platform.sessions.begin() as db:
            party = await party_for(db, player_id, lock=True)
            if party.leader_id != player_id:
                raise AppError(
                    403, "leader_required", "Only the party leader can queue"
                )
            member_ids = await members(db, party.id)
            roster = await profiles(db, member_ids)
            if len(roster) < 2 or len(roster) != len(member_ids):
                raise conflict(
                    "party_unavailable", "Queue with two to four active party members"
                )
            lineup = [
                roster[player_id],
                *(roster[member] for member in member_ids if member != player_id),
            ]
            return await self.lobby.join_party(party.id, lineup)
