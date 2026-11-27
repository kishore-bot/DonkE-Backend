from typing import Annotated

from fastapi import Depends

from app.core.dependencies import PlatformDep
from app.modules.lobby.dependencies import Lobby
from app.modules.social.services.friends import FriendsService
from app.modules.social.services.parties import PartyService
from app.modules.social.services.reports import ReportService
from app.modules.social.services.room_invites import RoomInviteService


async def get_friends(platform: PlatformDep, lobby: Lobby) -> FriendsService:
    return FriendsService(platform, lobby)


async def get_parties(platform: PlatformDep, lobby: Lobby) -> PartyService:
    return PartyService(platform, lobby)


async def get_room_invites(platform: PlatformDep, lobby: Lobby) -> RoomInviteService:
    return RoomInviteService(platform, lobby)


async def get_reports(platform: PlatformDep) -> ReportService:
    return ReportService(platform)


Friends = Annotated[FriendsService, Depends(get_friends)]
Parties = Annotated[PartyService, Depends(get_parties)]
RoomInvites = Annotated[RoomInviteService, Depends(get_room_invites)]
Reports = Annotated[ReportService, Depends(get_reports)]
