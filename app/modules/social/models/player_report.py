from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlayerReport(Base):
    __tablename__ = "player_reports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reporter_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(20))
    game_id: Mapped[UUID | None]
    note: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), server_default="open")
    resolution: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
