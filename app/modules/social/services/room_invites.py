from uuid import UUID

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.identity.schemas.profile import Profile
from app.modules.lobby.schemas.rooms import Room
from app.modules.lobby.services.lobby import LobbyService
from app.modules.social.helpers.errors import missing
from app.modules.social.helpers.moderation import pair
from app.modules.social.models.friendship import Friendship
from app.modules.social.repositories import invites as invites_repo
from app.modules.social.repositories.safety import blocked_with, ensure_not_blocked
from app.modules.social.schemas import invites as invites_schema
from app.modules.social.schemas.invites import InviteLink


class RoomInviteService:
    def __init__(self, platform: Platform, lobby: LobbyService):
        self.platform = platform
        self.lobby = lobby

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
        await invites_repo.add_room_invite(
            self.platform,
            friend,
            invites_schema.RoomInvite(
                room_id=room.id,
                from_id=profile.id,
                from_name=profile.display_name,
                expires_at=invites_repo.invite_expiry(),
            ),
        )

    async def room_invites(self, player_id: UUID) -> list[invites_schema.RoomInvite]:
        invites = await invites_repo.room_invites(self.platform, player_id)
        async with self.platform.sessions() as db:
            hidden = await blocked_with(db, player_id)
        return [invite for invite in invites if invite.from_id not in hidden]

    async def invite_link(
        self, profile: Profile, room_id: UUID, request_origin: str
    ) -> InviteLink:
        room = await self.member_room(profile, room_id)
        code = await invites_repo.create_link(self.platform, room.id, profile.id)
        base = (self.platform.settings.public_base_url or request_origin).rstrip("/")
        return InviteLink(
            code=code,
            url=f"{base}/?invite={code}",
            expires_in=invites_repo.LINK_SECONDS,
        )

    async def join_by_link(self, profile: Profile, code: str) -> Room:
        found = await invites_repo.resolve_link(self.platform, code)
        if found is None:
            raise missing("invite_not_found")
        room_id, inviter = found
        async with self.platform.sessions() as db:
            await ensure_not_blocked(db, profile.id, inviter)
        return await self.lobby.room("join_room", profile, room_id)
