from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.matches.models.match_player import MatchPlayer
from app.modules.matches.models.match_record import MatchRecord
from app.modules.matches.schemas.results import MatchReplay, RecentMatch


async def recent_results(platform: Platform, player_id: UUID) -> list[RecentMatch]:
    async with platform.sessions() as db:
        rows = await db.execute(
            select(MatchPlayer.game_id, MatchPlayer.finished_at)
            .where(MatchPlayer.player_id == player_id)
            .order_by(MatchPlayer.finished_at.desc(), MatchPlayer.game_id)
            .limit(10)
        )
        return [
            RecentMatch(game_id=game_id, finished_at=finished_at)
            for game_id, finished_at in rows
        ]


async def load_replay(platform: Platform, game_id: UUID) -> MatchReplay | None:
    async with platform.sessions() as db:
        record = await db.get(MatchRecord, game_id)
    return MatchReplay.model_validate(record.replay) if record else None


async def read_replay(
    platform: Platform, game_id: UUID, player_id: UUID
) -> MatchReplay:
    async with platform.sessions() as db:
        record = await db.get(MatchRecord, game_id)
        if record is not None:
            replay = MatchReplay.model_validate(record.replay)
            if any(seat.player_id == player_id for seat in replay.seats):
                return replay
    raise AppError(404, "game_not_found", "Match replay not found")
