import asyncio
import contextlib
import json
import logging
from typing import Literal
from uuid import UUID, uuid4

from donke_engine import OnlineGame
from redis.exceptions import RedisError

from app.core.platform import Platform
from app.modules.game.schemas.practice import PlayRequest
from app.modules.game.schemas.views import PlayerView
from app.modules.matches.helpers import bots
from app.modules.matches.helpers.rules import deadline, position, unavailable
from app.modules.matches.repositories.matches import (
    TURN_LEASE_MS,
    MatchConflict,
    MatchRepository,
)
from app.modules.matches.schemas.state import Acknowledgement, MatchState, PublicMatch
from app.modules.matches.services.lifecycle import settle_match, start_match

logger = logging.getLogger(__name__)
TURN_CONCURRENCY = 4


class MatchService:
    def __init__(self, platform: Platform):
        self.platform = platform
        self.repo = MatchRepository(platform)

    async def start(self, room_id: UUID) -> UUID | None:
        return await start_match(self.platform, self.repo, room_id)

    async def load(self, game_id: UUID, player_id: UUID) -> MatchState:
        state = await self.repo.get(game_id)
        if state is None:
            raise unavailable()
        position(state, player_id)
        return state

    def view(self, state: MatchState, player_id: UUID) -> PublicMatch:
        seat = position(state, player_id)
        game = OnlineGame.restore(state.native)
        view = PlayerView.model_validate_json(game.view(seat))
        if state.seats[seat].bot or state.status == "finished":
            view.legal_moves = []
        if state.status == "finished":
            view.turn = None
        return PublicMatch(
            id=state.id,
            status=state.status,
            sequence=state.sequence,
            version=state.version,
            turn_deadline_ms=state.deadline_ms if state.status == "active" else None,
            outcome=state.outcome,
            seats=state.seats,
            view=view,
            admission=state.admission,
        )

    async def play(
        self,
        game_id: UUID,
        player_id: UUID,
        owner: str,
        command: PlayRequest,
    ) -> Acknowledgement:
        state = await self.load(game_id, player_id)
        seat = position(state, player_id)
        signature = (
            f"{command.expected_version}:{command.card.suit}:{command.card.rank}"
        )
        identifier = f"{player_id}:{command.request_id}"
        await self.repo.execute("renew", game_id, player_id=str(player_id), owner=owner)
        recorded = await self.repo.cached_ack(game_id, identifier)
        if recorded is not None:
            if recorded["signature"] != signature:
                raise MatchConflict("request_id_reused")
            return Acknowledgement.model_validate(recorded)
        if state.version != command.expected_version:
            raise MatchConflict("stale_version")
        if state.status != "active":
            raise MatchConflict("game_finished")
        if state.seats[seat].bot or state.turn != seat:
            raise MatchConflict("out_of_turn")
        game = OnlineGame.restore(state.native)
        try:
            events = json.loads(game.play(seat, command.card.model_dump_json()))
        except ValueError as exc:
            raise MatchConflict(str(exc)) from exc
        # A legacy capped turn has no recoverable opening time.
        turn_opened = state.turn_opened_ms
        if turn_opened is None and state.deadline_ms < state.limit_ms:
            turn_opened = state.deadline_ms - max(
                1, round(self.platform.settings.turn_seconds * 1000)
            )
        if turn_opened is not None:
            think_ms = max(0, await self.repo.now_ms() - turn_opened)
            for event in events:
                if event.get("event") == "card_played":
                    event["think_ms"] = think_ms
        state.seats[seat].consecutive_timeouts = 0
        return await self.commit_play(
            state,
            game,
            events,
            owner,
            player_id=str(player_id),
            command=identifier,
            signature=signature,
        )

    async def leave(self, game_id: UUID, player_id: UUID, owner: str) -> None:
        state = await self.load(game_id, player_id)
        seat = position(state, player_id)
        game = OnlineGame.restore(state.native)
        view = PlayerView.model_validate_json(game.view(seat))
        if (
            state.status != "active"
            or seat in view.escape_order
            or state.seats[seat].bot
        ):
            return
        state.seats[seat].bot = True
        state.seats[seat].forfeited = True
        if state.turn == seat:
            state.deadline_ms = deadline(
                self.platform.settings, state, await self.repo.now_ms()
            )
        await self.commit(
            state,
            [{"event": "seat_taken_over", "seat": seat, "reason": "left"}],
            owner,
            player_id=str(player_id),
            is_leave=True,
        )

    async def on_deadline(self, game_id: UUID) -> None:
        owner = uuid4().hex
        if not await self.repo.acquire_turn(game_id, owner):
            return
        renew = asyncio.create_task(self.keep_turn_lease(game_id, owner))
        try:
            await self.play_due_turn(game_id, owner)
        except MatchConflict as error:
            if error.code not in {"turn_unclaimed", "game_finished", "stale_version"}:
                await self.defer("turn", game_id, error, owner=owner)
        except Exception as error:
            await self.defer("turn", game_id, error, owner=owner)
        finally:
            renew.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renew
            try:
                await self.repo.release_turn(game_id, owner)
            except RedisError as error:
                logger.warning(
                    "Turn lease will expire for %s (%s)", game_id, type(error).__name__
                )

    async def keep_turn_lease(self, game_id: UUID, owner: str) -> None:
        while True:
            await asyncio.sleep(TURN_LEASE_MS / 1_000 / 4)
            try:
                if not await self.repo.renew_turn(game_id, owner):
                    return
            except RedisError as error:
                logger.warning(
                    "Could not renew turn lease for %s (%s)",
                    game_id,
                    type(error).__name__,
                )
                # The commit still checks ownership. A transient failure may
                # recover before the current lease expires.

    async def play_due_turn(self, game_id: UUID, owner: str) -> None:
        state = await self.repo.get(game_id)
        if not state:
            await self.repo.execute("forget_missing", game_id, owner=owner)
            return
        now = await self.repo.now_ms()
        if state.turn is None or state.status != "active" or state.deadline_ms > now:
            return
        if now >= state.limit_ms:
            state.status = "finished"
            state.outcome = {"reason": "time_limit"}
            await self.commit(
                state, [{"event": "game_finished", "outcome": state.outcome}], owner
            )
            return
        seat = state.turn
        events = []
        human = not state.seats[seat].bot
        if human:
            player = state.seats[seat]
            player.timeouts += 1
            player.consecutive_timeouts += 1
            events.append({"event": "turn_timed_out", "seat": seat})
            if player.timeouts >= 5 or player.consecutive_timeouts >= 3:
                player.bot = True
                player.forfeited = True
                events.append(
                    {"event": "seat_taken_over", "seat": seat, "reason": "timeouts"}
                )
        game = OnlineGame.restore(state.native)
        if human:
            played = json.loads(game.play(seat))
            for event in played:
                if event.get("event") == "card_played":
                    event["auto"] = True  # Not a decision; analysis skips it.
        else:
            # Search is CPU work: run it in a thread so the worker's event loop
            # keeps serving claims, starts and other deadlines meanwhile. The
            # engine releases the GIL while it searches.
            card = await asyncio.to_thread(
                bots.choose,
                game,
                seat,
                state.seats[seat],
                bots.stable(state.id, state.version),
            )
            played = json.loads(game.play(seat, card))
            if state.seats[seat].player_id is not None:
                # A bot playing a human's seat after a leave or timeouts: never
                # count these engine moves as that human's decisions.
                for event in played:
                    if event.get("event") == "card_played":
                        event["auto"] = True
            played.extend(bots.persona_events(seat, state.seats[seat], played))
        events.extend(played)
        await self.commit_play(state, game, events, owner)

    async def commit_play(
        self,
        state: MatchState,
        game: OnlineGame,
        events: list[dict],
        owner: str,
        **context: str | int | bool,
    ) -> Acknowledgement:
        state.native, state.turn = game.snapshot(), game.turn
        now = await self.repo.now_ms()
        state.turn_opened_ms = now
        state.deadline_ms = deadline(self.platform.settings, state, now)
        if state.turn is None:
            state.status = "finished"
            state.outcome = next(
                event["outcome"]
                for event in events
                if event["event"] == "game_finished"
            )
        return await self.commit(state, events, owner, **context)

    async def commit(
        self,
        state: MatchState,
        events: list[dict],
        owner: str,
        **context: str | int | bool,
    ) -> Acknowledgement:
        expected = state.version
        state.version += 1
        state.sequence += 1
        result = await self.repo.execute(
            "commit",
            state.id,
            owner=owner,
            expected=expected,
            state=state.model_dump_json(),
            events=json.dumps(events),
            **context,
        )
        return Acknowledgement.model_validate(result)

    async def settle(self, game_id: UUID) -> None:
        await settle_match(self.platform, self.repo, game_id)

    async def start_ready_rooms(self) -> None:
        for room_id in await self.repo.due("rooms"):
            try:
                await self.start(room_id)
            except Exception as error:
                await self.defer("room", room_id, error)

    async def settle_finished(self) -> None:
        for game_id in await self.repo.due("settlement"):
            try:
                await self.settle(game_id)
            except Exception as error:
                await self.defer("settlement", game_id, error)

    async def tick(self) -> None:
        """Drive one cycle explicitly for scripts and tests."""
        await self.start_ready_rooms()
        limit = asyncio.Semaphore(TURN_CONCURRENCY)

        async def advance(game_id: UUID) -> None:
            async with limit:
                await self.on_deadline(game_id)

        await asyncio.gather(
            *(advance(game_id) for game_id in await self.repo.due("turns"))
        )
        await self.settle_finished()

    async def defer(
        self,
        work: Literal["room", "turn", "settlement"],
        identifier: UUID,
        error: Exception,
        *,
        owner: str = "",
    ) -> None:
        logger.warning(
            "Failed to process %s %s (%s)", work, identifier, type(error).__name__
        )
        try:
            await self.repo.execute(f"defer_{work}", identifier, owner=owner)
        except (MatchConflict, RedisError) as retry_error:
            logger.warning(
                "Could not schedule retry for %s %s (%s)",
                work,
                identifier,
                type(retry_error).__name__,
            )
