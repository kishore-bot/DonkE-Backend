"""Play and archive a demo match through the running HTTP and WebSocket APIs."""

import argparse
import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from httpx2 import AsyncClient, HTTPError, RequestError, Response
from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from app.modules.game.schemas import Card
from app.modules.lobby.schemas import Room
from app.modules.matches.schemas import Acknowledgement, MatchReplay, PublicMatch
from scripts.seed_demo import DemoSession, DemoSessions


class SmokeFailure(Exception):
    pass


def check(condition: bool, error: str) -> None:
    if not condition:
        raise SmokeFailure(error)


async def until[T](operation: Callable[[], Awaitable[T | None]]) -> T:
    while True:
        result = await operation()
        if result is not None:
            return result
        await asyncio.sleep(0.1)


def headers(session: DemoSession) -> dict[str, str]:
    return {"Authorization": f"Bearer {session.access_token}"}


def websocket_base(base: str) -> str:
    address = urlsplit(base)
    if (
        address.scheme not in {"http", "https"}
        or not address.hostname
        or address.username
        or address.password
        or address.path not in {"", "/"}
        or address.query
        or address.fragment
    ):
        raise SmokeFailure("Use an HTTP or HTTPS origin as the demo base URL")
    if address.scheme == "http" and address.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise SmokeFailure("Use HTTPS when sending demo tokens off loopback")
    return address._replace(
        scheme="wss" if address.scheme == "https" else "ws", path=""
    ).geturl()


class Peer:
    def __init__(self, socket: ClientConnection, cursor: int):
        self.socket = socket
        self.cursor = cursor
        self.state: PublicMatch | None = None

    async def receive(self) -> dict[str, Any]:
        message = json.loads(await self.socket.recv())
        match message["type"]:
            case "events":
                check(
                    message["sequence"] == self.cursor + 1,
                    "The public event stream skipped or repeated a sequence",
                )
                self.cursor = message["sequence"]
            case "state_sync":
                state = PublicMatch.model_validate(message)
                check(
                    state.sequence == self.cursor,
                    "The private snapshot and public event stream disagree",
                )
                self.state = state
            case "error":
                raise SmokeFailure(
                    f"The game rejected a demo command ({message['code']})"
                )
        return message

    async def snapshot(self, version: int = 0) -> PublicMatch:
        while self.state is None or self.state.version < version:
            await self.receive()
        return self.state

    async def play(self, version: int, card: Card, request_id: UUID) -> Acknowledgement:
        command = {
            "action": "play_card",
            "expected_version": version,
            "card": card.model_dump(),
            "request_id": str(request_id),
        }
        await self.socket.send(json.dumps(command))
        while True:
            message = await self.receive()
            if message["type"] == "ack":
                check(
                    message["request_id"] == str(request_id),
                    "The move acknowledgement used the wrong request ID",
                )
                return Acknowledgement.model_validate(message)


async def open_peer(
    stack: AsyncExitStack,
    base: str,
    game_id: UUID,
    session: DemoSession,
    cursor: int = 0,
) -> Peer:
    socket = await stack.enter_async_context(
        connect(
            f"{base}/api/v1/games/{game_id}/ws?after_sequence={cursor}",
            additional_headers=headers(session),
            proxy=None,
            close_timeout=2,
        )
    )
    return Peer(socket, cursor)


async def prepare_room(
    http: AsyncClient, players: tuple[DemoSession, DemoSession]
) -> UUID:
    host, guest = (headers(player) for player in players)
    room = Room.model_validate(
        (await http.post("/api/v1/rooms", headers=host, json={"capacity": 2}))
        .raise_for_status()
        .json()
    )
    path = f"/api/v1/rooms/{room.id}"
    (await http.post(f"{path}/join", headers=guest)).raise_for_status()
    for auth in host, guest:
        (
            await http.put(f"{path}/ready", headers=auth, json={"ready": True})
        ).raise_for_status()

    async def started() -> UUID | None:
        room_response = (await http.get(path, headers=host)).raise_for_status()
        return Room.model_validate(room_response.json()).game_id

    return await until(started)


async def play_match(
    base: str, game_id: UUID, players: tuple[DemoSession, DemoSession]
) -> int:
    rng = random.Random(game_id.int)
    async with AsyncExitStack() as stack:
        peers = [await open_peer(stack, base, game_id, player) for player in players]
        snapshots = await asyncio.gather(*(peer.snapshot() for peer in peers))
        opening = snapshots[0].view.turn
        if opening is None or snapshots[0].version != 0:
            raise SmokeFailure("The demo did not receive the opening turn")
        acting = peers[opening]
        opponent = 1 - opening
        before = peers[opponent].cursor
        await peers[opponent].socket.close()

        cards = snapshots[opening].view.legal_moves
        check(
            len(cards) == 1 and cards[0].rank == "Ace" and cards[0].suit == "Spades",
            "The opening move was not the Ace of Spades",
        )
        request = uuid4()
        ack = await acting.play(0, cards[0], request)
        retry = await acting.play(0, cards[0], request)
        check(
            retry == ack and ack.version == 1,
            "Retrying the opening changed its acknowledgement",
        )

        peers[opponent] = await open_peer(
            stack, base, game_id, players[opponent], before
        )
        synced = await peers[opponent].snapshot(ack.version)
        check(
            synced.sequence == ack.sequence and ack.sequence > before,
            "Reconnect did not replay the missed move",
        )
        snapshots = await asyncio.gather(
            *(peer.snapshot(ack.version) for peer in peers)
        )

        while snapshots[0].status == "active":
            turn = snapshots[0].view.turn
            if turn is None:
                raise SmokeFailure("An active game is missing its turn seat")
            state = snapshots[turn]
            check(bool(state.view.legal_moves), "The acting player has no legal move")
            check(
                len(state.view.hand) == state.view.card_counts[turn],
                "The private hand has an unexpected card count",
            )
            ack = await peers[turn].play(
                state.version, rng.choice(state.view.legal_moves), uuid4()
            )
            snapshots = await asyncio.gather(
                *(peer.snapshot(ack.version) for peer in peers)
            )
        return ack.sequence


async def smoke(base: str, data: DemoSessions, timeout: float) -> dict[str, Any]:
    ws_url = websocket_base(base)
    start = monotonic()
    async with (
        asyncio.timeout(timeout),
        AsyncClient(base_url=base, trust_env=False, timeout=5) as http,
    ):

        async def ready() -> bool | None:
            try:
                response = await http.get("/ready")
            except RequestError:
                return None
            return True if response.status_code == 200 else None

        await until(ready)
        auth = headers(data.players[0])
        sample = await http.get(f"/api/v1/games/{data.replay_id}/replay", headers=auth)
        check(
            sample.status_code == 200,
            "The seeded replay is missing or the demo token has expired",
        )
        game = await prepare_room(http, data.players)
        last = await play_match(ws_url, game, data.players)

        async def archived() -> Response | None:
            response = await http.get(f"/api/v1/games/{game}/replay", headers=auth)
            return None if response.status_code == 404 else response.raise_for_status()

        archive = MatchReplay.model_validate((await until(archived)).json())
        check(
            archive.events[-1].sequence == last,
            "The archived replay ends at the wrong sequence",
        )
        finish = archive.events[-1].events[-1]
        check(
            finish.get("event") == "game_finished"
            and finish.get("outcome") == archive.outcome,
            "The archived result does not match its terminal event",
        )
        ids = {str(seat.player_id) for seat in archive.seats}
        check(
            ids == {str(player.player_id) for player in data.players},
            "The archived seats do not match the demo players",
        )
    return {
        "game_id": str(game),
        "outcome": archive.outcome["reason"],
        "event_batches": last,
        "seconds": round(monotonic() - start, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("The smoke test timeout must be positive")
    try:
        data = DemoSessions.model_validate_json(args.sessions.read_bytes())
        print(
            json.dumps(
                asyncio.run(smoke(args.base_url, data, args.timeout)), sort_keys=True
            )
        )
    except (
        SmokeFailure,
        HTTPError,
        OSError,
        ValidationError,
        WebSocketException,
    ) as error:
        parser.exit(1, f"Demo smoke failed: {error}\n")


if __name__ == "__main__":
    main()
