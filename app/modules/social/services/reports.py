from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.platform import Platform
from app.modules.identity.repository import profiles
from app.modules.social.errors import missing
from app.modules.social.models import (
    PlayerReport,
)
from app.modules.social.safety import pair
from app.modules.social.schemas import (
    ReportCreate,
    ReportView,
)


class ReportService:
    def __init__(self, platform: Platform):
        self.platform = platform

    async def report(self, player_id: UUID, body: ReportCreate) -> ReportView:
        pair(player_id, body.player_id)
        async with self.platform.sessions.begin() as db:
            if body.player_id not in await profiles(db, [body.player_id]):
                raise missing("player_not_found")
            # One open report per reporter and target a day; repeats return it.
            existing = await db.scalar(
                select(PlayerReport).where(
                    PlayerReport.reporter_id == player_id,
                    PlayerReport.target_id == body.player_id,
                    PlayerReport.status == "open",
                    PlayerReport.created_at >= datetime.now(UTC) - timedelta(days=1),
                )
            )
            if existing is not None:
                return ReportView.model_validate(existing)
            report = PlayerReport(
                reporter_id=player_id,
                target_id=body.player_id,
                reason=body.reason,
                game_id=body.game_id,
                note=body.note,
            )
            db.add(report)
            await db.flush()
            await db.refresh(report)
            return ReportView.model_validate(report)
