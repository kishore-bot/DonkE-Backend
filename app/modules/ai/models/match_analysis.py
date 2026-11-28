from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Double, ForeignKey, Index, desc, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MatchAnalysis(Base):
    __tablename__ = "match_analyses"
    __table_args__ = (
        Index("match_analyses_player_recent", "player_id", desc("created_at")),
    )

    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    decisions: Mapped[int]
    accuracy: Mapped[float] = mapped_column(Double)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
