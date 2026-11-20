from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.rate_limit import limit
from app.modules.identity.router import CurrentPlayer, PlatformDep
from app.modules.lobby.repository import LobbyRepository
from app.modules.lobby.schemas import (
    QueueRequest,
    QueueStatus,
    ReadyRequest,
    Room,
    RoomCreate,
)
from app.modules.lobby.service import LobbyService

rooms = APIRouter(prefix="/api/v1/rooms", tags=["Rooms"])
matchmaking = APIRouter(prefix="/api/v1/matchmaking", tags=["Matchmaking"])


def get_lobby(platform: PlatformDep) -> LobbyService:
    return LobbyService(LobbyRepository(platform.redis, platform.settings))


Lobby = Annotated[LobbyService, Depends(get_lobby)]


async def lobby_write(player: CurrentPlayer, platform: PlatformDep) -> None:
    await limit(platform, "lobby_write", str(player.profile.id), 60, 60)


Writes = [Depends(lobby_write)]


@rooms.post("", status_code=201, dependencies=Writes)
async def create_room(body: RoomCreate, player: CurrentPlayer, lobby: Lobby) -> Room:
    return await lobby.create_room(player.profile, body.capacity)


@rooms.get("/{room_id}")
async def get_room(room_id: UUID, player: CurrentPlayer, lobby: Lobby) -> Room:
    return await lobby.room("get_room", player.profile, room_id)


@rooms.post("/{room_id}/join", dependencies=Writes)
async def join_room(room_id: UUID, player: CurrentPlayer, lobby: Lobby) -> Room:
    return await lobby.room("join_room", player.profile, room_id)


@rooms.put("/{room_id}/ready", dependencies=Writes)
async def ready(
    room_id: UUID, body: ReadyRequest, player: CurrentPlayer, lobby: Lobby
) -> Room:
    return await lobby.room("ready", player.profile, room_id, ready=body.ready)


@rooms.delete("/{room_id}/members/{player_id}", dependencies=Writes)
async def kick(
    room_id: UUID, player_id: UUID, player: CurrentPlayer, lobby: Lobby
) -> Room:
    return await lobby.room("kick", player.profile, room_id, target=str(player_id))


@rooms.post("/{room_id}/leave", status_code=204, dependencies=Writes)
async def leave_room(room_id: UUID, player: CurrentPlayer, lobby: Lobby) -> None:
    await lobby.leave_room(player.profile, room_id)


@matchmaking.post("/join", dependencies=Writes)
async def queue(body: QueueRequest, player: CurrentPlayer, lobby: Lobby) -> QueueStatus:
    return await lobby.join_queue(player.profile, body.mode)


@matchmaking.get("/status")
async def queue_status(player: CurrentPlayer, lobby: Lobby) -> QueueStatus:
    return await lobby.queue_status(player.profile)


@matchmaking.post("/cancel", dependencies=Writes)
async def cancel_queue(player: CurrentPlayer, lobby: Lobby) -> QueueStatus:
    return await lobby.cancel_queue(player.profile)
