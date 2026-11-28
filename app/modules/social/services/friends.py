from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.identity.repositories.players import profiles
from app.modules.lobby.services.lobby import LobbyService
from app.modules.matches.models.match_player import MatchPlayer
from app.modules.matches.models.match_record import MatchRecord
from app.modules.matches.schemas.results import MatchReplay
from app.modules.progression.services.analytics import finishing_ranks, match_analytics
from app.modules.social.helpers.errors import missing
from app.modules.social.helpers.moderation import pair
from app.modules.social.models.friendship import Friendship
from app.modules.social.models.party_invite import PartyInvite
from app.modules.social.models.party_member import PartyMember
from app.modules.social.models.player_block import PlayerBlock
from app.modules.social.repositories import presence
from app.modules.social.repositories.safety import ensure_not_blocked
from app.modules.social.schemas.friends import Activity, FriendStatus, Together


class FriendsService:
    def __init__(self, platform: Platform, lobby: LobbyService):
        self.platform = platform
        self.lobby = lobby

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
        present = await presence.online(self.platform, accepted)
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
