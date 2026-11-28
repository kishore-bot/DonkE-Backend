from uuid import UUID

from fastapi import APIRouter

from app.modules.identity.dependencies import CurrentPlayer, PlayerWrites
from app.modules.lobby.dependencies import Lobby
from app.modules.lobby.schemas.queue import QueueRequest, QueueStatus
from app.modules.lobby.schemas.rooms import ReadyRequest, Room, RoomCreate

rooms = APIRouter(prefix="/api/v1/rooms", tags=["Rooms"])
matchmaking = APIRouter(prefix="/api/v1/matchmaking", tags=["Matchmaking"])


@rooms.post("", status_code=201, dependencies=PlayerWrites)
async def create_room(body: RoomCreate, player: CurrentPlayer, lobby: Lobby) -> Room:
    return await lobby.create_room(player.profile, body.capacity)


@rooms.get("/{room_id}")
async def get_room(room_id: UUID, player: CurrentPlayer, lobby: Lobby) -> Room:
    return await lobby.room("get_room", player.profile, room_id)


@rooms.post("/{room_id}/join", dependencies=PlayerWrites)
async def join_room(room_id: UUID, player: CurrentPlayer, lobby: Lobby) -> Room:
    return await lobby.room("join_room", player.profile, room_id)


@rooms.put("/{room_id}/ready", dependencies=PlayerWrites)
async def ready(
    room_id: UUID, body: ReadyRequest, player: CurrentPlayer, lobby: Lobby
) -> Room:
    return await lobby.room("ready", player.profile, room_id, ready=body.ready)


@rooms.delete("/{room_id}/members/{player_id}", dependencies=PlayerWrites)
async def kick(
    room_id: UUID, player_id: UUID, player: CurrentPlayer, lobby: Lobby
) -> Room:
    return await lobby.room("kick", player.profile, room_id, target=str(player_id))


@rooms.post("/{room_id}/leave", status_code=204, dependencies=PlayerWrites)
async def leave_room(room_id: UUID, player: CurrentPlayer, lobby: Lobby) -> None:
    await lobby.leave_room(player.profile, room_id)


@matchmaking.post("/join", dependencies=PlayerWrites)
async def queue(body: QueueRequest, player: CurrentPlayer, lobby: Lobby) -> QueueStatus:
    return await lobby.join_queue(player.profile, body.mode)


@matchmaking.get("/status")
async def queue_status(player: CurrentPlayer, lobby: Lobby) -> QueueStatus:
    return await lobby.queue_status(player.profile)


@matchmaking.post("/cancel", dependencies=PlayerWrites)
async def cancel_queue(player: CurrentPlayer, lobby: Lobby) -> QueueStatus:
    return await lobby.cancel_queue(player.profile)
