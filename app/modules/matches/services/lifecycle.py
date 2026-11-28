import json
from datetime import UTC, datetime
from math import ceil
from uuid import UUID, uuid4

from donke_engine import OnlineGame

from app.core.platform import Platform
from app.modules.identity.repositories.players import profiles
from app.modules.matches.helpers import bots
from app.modules.matches.helpers.rules import deadline
from app.modules.matches.repositories.matches import MatchConflict, MatchRepository
from app.modules.matches.schemas.results import MatchReplay
from app.modules.matches.schemas.state import GameSeat, MatchState
from app.modules.matches.services import settlement
from app.modules.progression.services.seasons import (
    lock_season_schedule,
    match_admission,
)


async def start_match(
    platform: Platform, repo: MatchRepository, room_id: UUID
) -> UUID | None:
    room = await repo.room(room_id)
    if room is None or room.game_id is not None:
        await platform.redis.zrem(f"{repo.prefix}:lobby:rooms:ready", str(room_id))
        return room.game_id if room is not None else None
    if room.status != "ready":
        return None
    game = OnlineGame(len(room.seats))
    game_id = uuid4()
    seats = [GameSeat(**seat.model_dump()) for seat in room.seats]
    humans = [seat.player_id for seat in seats if seat.player_id and not seat.bot]
    async with platform.sessions() as db:
        mmrs = {
            player: profile.mmr
            for player, profile in (await profiles(db, humans)).items()
        }
    rival = bots.assign(seats, mmrs, game_id)
    prep_ms = round(platform.settings.hand_prep_seconds * 1000)
    opening_events: list[dict] = [
        {"event": "hand_dealt"}
        if prep_ms
        else {"event": "game_started", "turn": game.turn}
    ]
    if rival is not None:
        opening_events.append(
            {
                "event": "rival_joined",
                "seat": rival,
                "persona": seats[rival].persona,
                "player_id": str(seats[rival].rival_of),
            }
        )
    opening = game.snapshot()
    try:
        async with platform.sessions.begin() as db:
            await lock_season_schedule(db, read=True)
            now = await repo.now_ms()
            admitted_at = datetime.fromtimestamp(now / 1000, UTC)
            admission, boundary = await match_admission(db, admitted_at)
            state = MatchState(
                id=game_id,
                room_id=room.id,
                mode=room.mode,
                seats=seats,
                native=opening,
                opening=opening,
                started_ms=now,
                turn=game.turn,
                deadline_ms=now,
                turn_opened_ms=None if prep_ms else now,
                prepare_until_ms=now + prep_ms if prep_ms else None,
                limit_ms=now + prep_ms + platform.settings.match_minutes * 60_000,
                admission=admission,
            )
            state.deadline_ms = state.prepare_until_ms or deadline(
                platform.settings, state, now
            )
            guard = (
                {"admit_before_ms": ceil(boundary.timestamp() * 1000)}
                if boundary is not None
                else {}
            )
            result = await repo.execute(
                "start",
                state.id,
                room_id=str(room.id),
                room_revision=room.revision,
                state=state.model_dump_json(),
                events=json.dumps(opening_events),
                **guard,
            )
    except MatchConflict as exc:
        if exc.code in {"room_changed", "room_missing", "season_boundary"}:
            return None
        raise
    return UUID(result["game_id"])


async def settle_match(
    platform: Platform, repo: MatchRepository, game_id: UUID
) -> None:
    prepared = await repo.prepare_settlement(game_id)
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
        events=await repo.events(game_id, 0, state.sequence),
        opening=state.opening,
        admission=state.admission,
    )
    await settlement.persist(platform, replay, finished_at=finished_at)
    await repo.execute(
        "settled", game_id, retention=platform.settings.match_archive_seconds
    )
