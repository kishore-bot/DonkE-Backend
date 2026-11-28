import asyncio
import contextlib
from time import monotonic
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Response, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from redis.exceptions import RedisError

from app.core.dependencies import PlatformDep
from app.core.errors import AppError, ErrorResponse
from app.core.platform import Platform
from app.core.rate_limit import limit
from app.modules.identity.dependencies import CurrentPlayer
from app.modules.identity.dto.principal import Principal
from app.modules.identity.services.identity import IdentityService
from app.modules.matches.helpers.rules import position
from app.modules.matches.repositories.matches import MatchConflict
from app.modules.matches.schemas.socket import (
    COMMAND,
    SocketChat,
    SocketEmote,
    SocketLeave,
    SocketPlay,
    SocketTicket,
)
from app.modules.matches.services import socket_tickets
from app.modules.matches.services.match import MatchService
from app.modules.social.helpers import redis_keys
from app.modules.social.helpers.moderation import clean
from app.modules.social.repositories import feed, presence
from app.modules.social.repositories.safety import (
    allowed_emote,
    blocked_with,
    ensure_can_chat,
)

router = APIRouter()


async def send(socket: WebSocket, data: dict) -> None:
    await asyncio.wait_for(socket.send_json(data), timeout=3)


async def socket_loop(
    socket: WebSocket,
    service: MatchService,
    principal: Principal,
    game_id: UUID,
    owner: str,
    after: int,
) -> None:
    player_id = principal.profile.id
    identity = IdentityService(service.platform)

    async def sync(last: int) -> int:
        state = await service.load_for_socket(game_id, player_id)
        if last > state.sequence:
            raise MatchConflict("invalid_sequence")
        if state.sequence > last:
            for batch in await service.repo.events(game_id, last, state.sequence):
                await send(socket, {"type": "events", **batch.model_dump(mode="json")})
        await send(
            socket,
            {
                "type": "state_sync",
                **service.view(
                    state, player_id, now_ms=await service.repo.now_ms()
                ).model_dump(mode="json"),
            },
        )
        return state.sequence

    async def social(command: SocketEmote | SocketChat) -> None:
        """Emotes and table chat go to a side feed, never the game log, so
        they cannot change the game version clients play against."""
        platform = service.platform
        state = await service.load_for_socket(game_id, player_id)
        seat = position(state, player_id)
        async with platform.sessions() as db:
            if isinstance(command, SocketEmote):
                await limit(platform, "emote", str(player_id), 6, 10)
                value = await allowed_emote(db, player_id, command.emote)
                await feed.post_feed(platform, game_id, seat, "emote", value)
            else:
                await limit(platform, "table_chat", str(player_id), 5, 3)
                await ensure_can_chat(db, player_id)
                await feed.post_feed(
                    platform, game_id, seat, "chat", clean(command.text)
                )

    seat_players = [
        seat.player_id
        for seat in (await service.load_for_socket(game_id, player_id)).seats
    ]

    async def forward_feed(last: str | None) -> str | None:
        entries = await feed.read_feed(service.platform, game_id, last)
        if not entries:
            return last
        # Blocks are read fresh for every batch, so blocking someone mid-match
        # hides their very next message. Idle sockets never query.
        async with service.platform.sessions() as db:
            hidden = await blocked_with(db, player_id)
        for entry in entries:
            last = entry["id"]
            if seat_players[entry["seat"]] not in hidden:
                await send(socket, {"type": "feed", **entry})
        return last

    events_key = service.repo.game_key("events", game_id)
    feed_key = redis_keys.key(service.platform, "feed", game_id)
    cursor = await sync(after)
    feed_cursor = await forward_feed(None)
    next_auth = monotonic() + 5
    next_renew = 0.0
    pending = asyncio.create_task(socket.receive())
    try:
        while True:
            if monotonic() >= next_auth:
                await identity.active_session(player_id, principal.session_id)
                await presence.touch(service.platform, player_id)
                next_auth = monotonic() + 5
            # The 15 s connection lease is renewed every 3 s, not every tick;
            # a replaced connection is noticed at the next renewal.
            renewed = monotonic() >= next_renew
            if renewed:
                await service.repo.execute(
                    "renew", game_id, player_id=str(player_id), owner=owner
                )
                next_renew = monotonic() + 3
            done, _ = await asyncio.wait({pending}, timeout=0.3)
            if done:
                frame = pending.result()
                if frame["type"] == "websocket.disconnect":
                    return
                text = frame.get("text")
                if text is None:
                    await socket.close(code=1003)
                    return
                if len(text.encode()) > 8192:
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
                    elif isinstance(command, SocketEmote | SocketChat):
                        try:
                            await social(command)
                        except AppError as exc:
                            await send(socket, {"type": "error", "code": exc.code})
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
            # Idle ticks run one non-blocking XREAD over the event and feed
            # streams instead of reading the match state. Event ids are
            # `{sequence}-0`, so any entry past the cursor means new moves.
            # A full load still runs on each renewal, to notice a deleted game.
            fresh = await service.platform.redis.xread(
                {events_key: f"{cursor}-0", feed_key: feed_cursor or "0-0"}, count=1
            )
            streams = set(fresh) if isinstance(fresh, dict) else {s for s, _ in fresh}
            if renewed or events_key in streams:
                state = await service.load_for_socket(game_id, player_id)
                if state.sequence != cursor:
                    cursor = await sync(cursor)
            if feed_key in streams:
                feed_cursor = await forward_feed(feed_cursor)
    finally:
        if not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending


@router.post(
    "/{game_id}/ws-ticket",
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
async def issue_socket_ticket(
    game_id: UUID, player: CurrentPlayer, platform: PlatformDep, response: Response
) -> SocketTicket:
    """Mint a single-use browser ticket for a seated player. Expires in 30 seconds."""
    await MatchService(platform).load_for_socket(game_id, player.profile.id)
    await limit(platform, "ws_ticket", str(player.profile.id), 30, 60)
    response.headers["Cache-Control"] = "no-store"
    return SocketTicket(ticket=await socket_tickets.issue(platform, game_id, player))


@router.websocket("/{game_id}/ws")
async def multiplayer(
    websocket: WebSocket,
    game_id: UUID,
    after_sequence: Annotated[int, Query(ge=0, le=1020)] = 0,
) -> None:
    platform: Platform | None = websocket.app.state.platform
    scheme, _, token = websocket.headers.get("authorization", "").partition(" ")
    if platform is None:
        await websocket.close(code=4401)
        return
    subprotocol = None
    try:
        if scheme.lower() == "bearer" and token:
            principal = await IdentityService(platform).authenticate(token)
        else:
            transport = "https" if websocket.url.scheme == "wss" else "http"
            principal = await socket_tickets.redeem(
                platform,
                game_id,
                websocket.scope.get("subprotocols", []),
                websocket.headers.getlist("origin"),
                f"{transport}://{websocket.url.netloc}",
            )
            subprotocol = socket_tickets.PROTOCOL
        player_id = principal.profile.id
        service = MatchService(platform)
        state = await service.load_for_socket(game_id, player_id)
    except AppError as exc:
        await websocket.close(code=4401 if exc.status == 401 else 4404)
        return
    except RedisError, TimeoutError:
        await websocket.close(code=1013)
        return
    await websocket.accept(subprotocol=subprotocol)
    if after_sequence > state.sequence:
        await websocket.close(code=4409, reason="invalid_sequence")
        return
    owner = uuid4().hex
    try:
        await service.repo.connect(game_id, player_id, owner)
        await socket_loop(websocket, service, principal, game_id, owner, after_sequence)
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
