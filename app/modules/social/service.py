from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.identity.repository import profiles
from app.modules.identity.schemas import Profile
from app.modules.lobby.repository import LobbyRepository
from app.modules.lobby.schemas import QueueStatus, Room
from app.modules.lobby.service import LobbyService
from app.modules.matches.models import MatchPlayer, MatchRecord
from app.modules.matches.schemas import MatchReplay
from app.modules.progression.analytics import finishing_ranks, match_analytics
from app.modules.social import live
from app.modules.social.models import (
    Friendship,
    Party,
    PartyInvite,
    PartyMember,
    PlayerBlock,
    PlayerReport,
)
from app.modules.social.safety import blocked_with, ensure_not_blocked
from app.modules.social.schemas import (
    Activity,
    FriendStatus,
    InviteLink,
    PartyView,
    ReportCreate,
    ReportView,
    Together,
)


def missing(code: str) -> AppError:
    return AppError(404, code, "Social record not found")


def conflict(code: str, detail: str) -> AppError:
    return AppError(409, code, detail)


def pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    if first == second:
        raise AppError(422, "self_request", "Choose another player")
    return (first, second) if first < second else (second, first)


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


class SocialService:
    def __init__(self, platform: Platform):
        self.platform = platform
        self.lobby = LobbyService(LobbyRepository(platform.redis, platform.settings))

    async def friends(self, player_id: UUID) -> list[FriendStatus]:
        async with self.platform.sessions() as db:
            edges = list(
                await db.scalars(
                    select(Friendship)
                    .where(
                        or_(
                            Friendship.first_id == player_id,
                            Friendship.second_id == player_id,
                        )
                    )
                    .order_by(Friendship.first_id, Friendship.second_id)
                )
            )
            others = [
                edge.second_id if edge.first_id == player_id else edge.first_id
                for edge in edges
            ]
            known = await profiles(db, others)
        accepted = [
            other
            for edge, other in zip(edges, others, strict=True)
            if edge.accepted and other in known
        ]
        present = await live.online(self.platform, accepted)
        activity: dict[UUID, Activity] = {
            other: (await self.lobby.queue_status(known[other])).status
            for other in accepted
        }
        return [
            FriendStatus(
                player=known[other],
                status="friends"
                if edge.accepted
                else "outgoing"
                if edge.requester_id == player_id
                else "incoming",
                online=other in present,
                activity=activity.get(other),
            )
            for edge, other in zip(edges, others, strict=True)
            if other in known
        ]

    async def request(self, player_id: UUID, other: UUID) -> None:
        first, second = pair(player_id, other)
        async with self.platform.sessions.begin() as db:
            if other not in await profiles(db, [other]):
                raise missing("player_not_found")
            await ensure_not_blocked(db, player_id, other)
            await db.execute(
                insert(Friendship)
                .values(
                    first_id=first,
                    second_id=second,
                    requester_id=player_id,
                )
                .on_conflict_do_nothing()
            )

    async def update_friend(
        self, player_id: UUID, other: UUID, *, accept: bool
    ) -> None:
        async with self.platform.sessions.begin() as db:
            edge = await db.get(
                Friendship, pair(player_id, other), with_for_update=True
            )
            if edge is None:
                if accept:
                    raise missing("friend_request_not_found")
                return
            if not accept:
                await db.delete(edge)
            elif not edge.accepted and edge.requester_id == player_id:
                raise AppError(
                    403, "recipient_required", "Only the recipient can accept"
                )
            else:
                edge.accepted = True

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

    # Blocking ------------------------------------------------------------

    async def block(self, player_id: UUID, other: UUID) -> None:
        first, second = pair(player_id, other)
        async with self.platform.sessions.begin() as db:
            if other not in await profiles(db, [other]):
                raise missing("player_not_found")
            await db.execute(
                insert(PlayerBlock)
                .values(blocker_id=player_id, blocked_id=other)
                .on_conflict_do_nothing()
            )
            # A block ends the friendship and any pending party invites.
            await db.execute(
                delete(Friendship).where(
                    Friendship.first_id == first, Friendship.second_id == second
                )
            )
            for host, guest in ((player_id, other), (other, player_id)):
                parties = select(PartyMember.party_id).where(
                    PartyMember.player_id == host
                )
                await db.execute(
                    delete(PartyInvite).where(
                        PartyInvite.player_id == guest,
                        PartyInvite.party_id.in_(parties),
                    )
                )

    async def unblock(self, player_id: UUID, other: UUID) -> None:
        async with self.platform.sessions.begin() as db:
            await db.execute(
                delete(PlayerBlock).where(
                    PlayerBlock.blocker_id == player_id, PlayerBlock.blocked_id == other
                )
            )

    async def blocks(self, player_id: UUID) -> list[UUID]:
        async with self.platform.sessions() as db:
            return list(
                await db.scalars(
                    select(PlayerBlock.blocked_id)
                    .where(PlayerBlock.blocker_id == player_id)
                    .order_by(PlayerBlock.created_at)
                )
            )

    # Head-to-head --------------------------------------------------------

    async def together(self, player_id: UUID, other: UUID) -> Together:
        pair(player_id, other)

        mine, theirs = aliased(MatchPlayer), aliased(MatchPlayer)
        async with self.platform.sessions() as db:
            # Index walk: this player's recent matches joined to the other's.
            records = list(
                await db.scalars(
                    select(MatchRecord)
                    .join(mine, mine.game_id == MatchRecord.id)
                    .join(theirs, theirs.game_id == MatchRecord.id)
                    .where(mine.player_id == player_id, theirs.player_id == other)
                    .order_by(mine.finished_at.desc())
                    .limit(200)
                )
            )
        totals = Together(
            games=0, ahead=0, behind=0, tied=0, my_donkeys=0, their_donkeys=0
        )
        for record in records:
            replay = MatchReplay.model_validate(record.replay)
            stats = match_analytics(replay)
            ranks = finishing_ranks(stats)
            seats = {seat.player_id: seat.seat for seat in stats.seats}
            mine, theirs = seats[player_id], seats[other]
            totals.games += 1
            if ranks[mine] < ranks[theirs]:
                totals.ahead += 1
            elif ranks[mine] > ranks[theirs]:
                totals.behind += 1
            else:
                totals.tied += 1
            totals.my_donkeys += int(stats.seats[mine].donkey)
            totals.their_donkeys += int(stats.seats[theirs].donkey)
        return totals

    # Room invites and links -------------------------------------------------

    async def member_room(self, profile: Profile, room_id: UUID) -> Room:
        room = await self.lobby.room("get_room", profile, room_id)
        if all(seat.player_id != profile.id for seat in room.seats):
            raise AppError(403, "room_member_required", "Join the room first")
        return room

    async def invite_to_room(
        self, profile: Profile, room_id: UUID, friend: UUID
    ) -> None:
        room = await self.member_room(profile, room_id)
        async with self.platform.sessions() as db:
            edge = await db.get(Friendship, pair(profile.id, friend))
            if edge is None or not edge.accepted:
                raise AppError(403, "friend_required", "Invite an accepted friend")
            await ensure_not_blocked(db, profile.id, friend)
        await live.add_room_invite(
            self.platform,
            friend,
            live.RoomInvite(
                room_id=room.id,
                from_id=profile.id,
                from_name=profile.display_name,
                expires_at=live.invite_expiry(),
            ),
        )

    async def room_invites(self, player_id: UUID) -> list[live.RoomInvite]:
        invites = await live.room_invites(self.platform, player_id)
        async with self.platform.sessions() as db:
            hidden = await blocked_with(db, player_id)
        return [invite for invite in invites if invite.from_id not in hidden]

    async def invite_link(
        self, profile: Profile, room_id: UUID, request_origin: str
    ) -> InviteLink:
        room = await self.member_room(profile, room_id)
        code = await live.create_link(self.platform, room.id, profile.id)
        base = (self.platform.settings.public_base_url or request_origin).rstrip("/")
        return InviteLink(
            code=code,
            url=f"{base}/?invite={code}",
            expires_in=live.LINK_SECONDS,
        )

    async def join_by_link(self, profile: Profile, code: str) -> Room:
        found = await live.resolve_link(self.platform, code)
        if found is None:
            raise missing("invite_not_found")
        room_id, inviter = found
        async with self.platform.sessions() as db:
            await ensure_not_blocked(db, profile.id, inviter)
        return await self.lobby.room("join_room", profile, room_id)

    # Reports ---------------------------------------------------------------

    async def report(self, player_id: UUID, body: ReportCreate) -> ReportView:
        pair(player_id, body.player_id)
        async with self.platform.sessions.begin() as db:
            if body.player_id not in await profiles(db, [body.player_id]):
                raise missing("player_not_found")
            # One open report per reporter and target a day; repeats return it.
            existing = await db.scalar(
                select(PlayerReport).where(
                    PlayerReport.reporter_id == player_id,
                    PlayerReport.target_id == body.player_id,
                    PlayerReport.status == "open",
                    PlayerReport.created_at >= datetime.now(UTC) - timedelta(days=1),
                )
            )
            if existing is not None:
                return ReportView.model_validate(existing)
            report = PlayerReport(
                reporter_id=player_id,
                target_id=body.player_id,
                reason=body.reason,
                game_id=body.game_id,
                note=body.note,
            )
            db.add(report)
            await db.flush()
            await db.refresh(report)
            return ReportView.model_validate(report)
