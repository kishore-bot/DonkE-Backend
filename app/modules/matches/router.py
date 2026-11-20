import asyncio
import contextlib
from time import monotonic
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from redis.exceptions import RedisError

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.game.schemas import PlayRequest
from app.modules.identity.router import CurrentPlayer, PlatformDep
from app.modules.identity.service import IdentityService
from app.modules.matches import settlement
from app.modules.matches.repository import MatchConflict
from app.modules.matches.schemas import MatchReplay
from app.modules.matches.service import MatchService

router = APIRouter(prefix="/api/v1/games", tags=["Multiplayer"])


class SocketPlay(PlayRequest):
    action: Literal["play_card"]


class SocketLeave(BaseModel):
    action: Literal["leave"]


class SocketPing(BaseModel):
    action: Literal["ping"]


Command = Annotated[
    SocketPlay | SocketLeave | SocketPing, Field(discriminator="action")
]
COMMAND = TypeAdapter(Command)


@router.get("/{game_id}/replay")
async def replay(
    game_id: UUID, player: CurrentPlayer, platform: PlatformDep
) -> MatchReplay:
    return await settlement.read_replay(platform, game_id, player.profile.id)


async def send(socket: WebSocket, data: dict) -> None:
    await asyncio.wait_for(socket.send_json(data), timeout=3)


async def socket_loop(
    socket: WebSocket,
    service: MatchService,
    token: str,
    player_id: UUID,
    game_id: UUID,
    owner: str,
    after: int,
) -> None:
    async def sync(last: int) -> int:
        state = await service.load(game_id, player_id)
        if last > state.sequence:
            raise MatchConflict("invalid_sequence")
        if state.sequence > last:
            for batch in await service.repo.events(game_id, last, state.sequence):
                await send(socket, {"type": "events", **batch.model_dump(mode="json")})
        await send(
            socket,
            {
                "type": "state_sync",
                **service.view(state, player_id).model_dump(mode="json"),
            },
        )
        return state.sequence

    cursor = await sync(after)
    next_auth = monotonic() + 5
    pending = asyncio.create_task(socket.receive())
    try:
        while True:
            if monotonic() >= next_auth:
                await IdentityService(service.platform).authenticate(token)
                next_auth = monotonic() + 5
            await service.repo.execute(
                "renew", game_id, player_id=str(player_id), owner=owner
            )
            done, _ = await asyncio.wait({pending}, timeout=0.3)
            if done:
                frame = pending.result()
                if frame["type"] == "websocket.disconnect":
                    return
                text = frame.get("text")
                if text is None or len(text.encode()) > 8192:
                    await socket.close(code=1009)
                    return
                try:
                    command = COMMAND.validate_json(text)
                    if isinstance(command, SocketPlay):
                        ack = await service.play(game_id, player_id, owner, command)
                        await send(
                            socket,
                            {
                                "type": "ack",
                                "request_id": str(command.request_id),
                                **ack.model_dump(),
                            },
                        )
                    elif isinstance(command, SocketLeave):
                        await service.leave(game_id, player_id, owner)
                        await send(socket, {"type": "left"})
                        await socket.close()
                        return
                    else:
                        await send(socket, {"type": "pong"})
                except ValidationError:
                    await send(socket, {"type": "error", "code": "invalid_command"})
                except MatchConflict as exc:
                    if exc.code == "connection_replaced":
                        raise
                    await send(socket, {"type": "error", "code": exc.code})
                pending = asyncio.create_task(socket.receive())
            state = await service.load(game_id, player_id)
            if state.sequence != cursor:
                cursor = await sync(cursor)
    finally:
        if not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending


@router.websocket("/{game_id}/ws")
async def multiplayer(
    websocket: WebSocket,
    game_id: UUID,
    after_sequence: Annotated[int, Query(ge=0, le=1020)] = 0,
) -> None:
    platform: Platform | None = websocket.app.state.platform
    scheme, _, token = websocket.headers.get("authorization", "").partition(" ")
    if platform is None or scheme.lower() != "bearer" or not token:
        await websocket.close(code=4401)
        return
    try:
        principal = await IdentityService(platform).authenticate(token)
        player_id = principal.profile.id
        service = MatchService(platform)
        await service.load(game_id, player_id)
    except AppError as exc:
        await websocket.close(code=4401 if exc.status == 401 else 4404)
        return
    owner = uuid4().hex
    await websocket.accept()
    try:
        await service.repo.connect(game_id, player_id, owner)
        await socket_loop(
            websocket, service, token, player_id, game_id, owner, after_sequence
        )
    except WebSocketDisconnect:
        pass
    except MatchConflict as exc:
        await websocket.close(code=4409, reason=exc.code)
    except AppError as exc:
        await websocket.close(code=4401 if exc.status == 401 else 4404)
    except RedisError, TimeoutError:
        await websocket.close(code=1013)
    finally:
        with contextlib.suppress(MatchConflict, RedisError):
            await service.repo.execute(
                "disconnect", game_id, player_id=str(player_id), owner=owner
            )
