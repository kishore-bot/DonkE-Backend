import json
import logging
from uuid import UUID, uuid4

from donke_engine import OnlineGame
from redis.exceptions import RedisError

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.game.schemas import PlayerView, PlayRequest
from app.modules.matches import settlement
from app.modules.matches.repository import MatchConflict, MatchRepository
from app.modules.matches.schemas import (
    Acknowledgement,
    GameSeat,
    MatchReplay,
    MatchState,
    PublicMatch,
)

logger = logging.getLogger(__name__)


def unavailable() -> AppError:
    return AppError(404, "game_not_found", "Match not found")


def position(state: MatchState, player_id: UUID) -> int:
    for index, seat in enumerate(state.seats):
        if seat.player_id == player_id:
            return index
    raise unavailable()


class MatchService:
    def __init__(self, platform: Platform):
        self.platform = platform
        self.repo = MatchRepository(platform)

    def deadline(self, state: MatchState, now: int) -> int:
        if state.turn is None:
            return now
        config = self.platform.settings
        delay = (
            config.bot_turn_seconds
            if state.seats[state.turn].bot
            else config.turn_seconds
        )
        return min(state.limit_ms, now + max(1, round(delay * 1000)))

    async def start(self, room_id: UUID) -> UUID | None:
        room = await self.repo.room(room_id)
        if room is None or room.game_id is not None:
            await self.platform.redis.zrem(
                f"{self.repo.prefix}:lobby:rooms:ready", str(room_id)
            )
            return room.game_id if room is not None else None
        if room.status != "ready":
            return None
        game = OnlineGame(len(room.seats))
        now = await self.repo.now_ms()
        state = MatchState(
            id=uuid4(),
            room_id=room.id,
            mode=room.mode,
            seats=[GameSeat(**seat.model_dump()) for seat in room.seats],
            native=game.snapshot(),
            opening=game.snapshot(),
            started_ms=now,
            turn=game.turn,
            deadline_ms=now,
            limit_ms=now + self.platform.settings.match_minutes * 60_000,
        )
        state.deadline_ms = self.deadline(state, now)
        try:
            result = await self.repo.execute(
                "start",
                state.id,
                room_id=str(room.id),
                room_revision=room.revision,
                state=state.model_dump_json(),
                events=json.dumps([{"event": "game_started", "turn": state.turn}]),
            )
        except MatchConflict as exc:
            if exc.code in {"room_changed", "room_missing"}:
                return None
            raise
        return UUID(result["game_id"])

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
            state.deadline_ms = self.deadline(state, await self.repo.now_ms())
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
        state = await self.repo.get(game_id)
        if not state:
            await self.platform.redis.zrem(
                self.repo.game_key("index", "turns"), str(game_id)
            )
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
        if not state.seats[seat].bot:
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
        events.extend(json.loads(game.play(seat)))
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
        state.deadline_ms = self.deadline(state, await self.repo.now_ms())
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
        prepared = await self.repo.prepare_settlement(game_id)
        if prepared is None:
            return
        state, finished_at = prepared
        if state.outcome is None:
            raise MatchConflict("outcome_missing")
        replay = MatchReplay(
            id=state.id,
            room_id=state.room_id,
            mode=state.mode,
            seats=state.seats,
            outcome=state.outcome,
            events=await self.repo.events(game_id, 0, state.sequence),
            opening=state.opening,
        )
        await settlement.persist(self.platform, replay, finished_at=finished_at)
        await self.repo.execute(
            "settled", game_id, retention=self.platform.settings.match_archive_seconds
        )

    async def tick(self) -> None:
        for room_id in await self.repo.due("unused", lobby=True):
            try:
                await self.start(room_id)
            except Exception as error:  # noqa: BLE001 - Keep processing other rooms.
                await self.defer("room", room_id, error)
        for game_id in await self.repo.due("turns"):
            try:
                await self.on_deadline(game_id)
            except MatchConflict as exc:
                if exc.code not in {"turn_unclaimed", "game_finished", "stale_version"}:
                    await self.defer("turn", game_id, exc)
            except Exception as error:  # noqa: BLE001 - Keep processing other turns.
                await self.defer("turn", game_id, error)
        for game_id in await self.repo.due("settlement"):
            try:
                await self.settle(game_id)
            except Exception as error:  # noqa: BLE001 - Keep processing other results.
                await self.defer("settlement", game_id, error)

    async def defer(self, work: str, identifier: UUID, error: Exception) -> None:
        logger.warning(
            "Failed to process %s %s (%s)", work, identifier, type(error).__name__
        )
        try:
            await self.repo.execute(f"defer_{work}", identifier)
        except (MatchConflict, RedisError) as retry_error:
            logger.warning(
                "Could not schedule retry for %s %s (%s)",
                work,
                identifier,
                type(retry_error).__name__,
            )
