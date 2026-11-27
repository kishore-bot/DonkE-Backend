from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, desc, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MatchRecord(Base):
    __tablename__ = "matches"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    replay: Mapped[dict[str, Any]] = mapped_column(JSONB)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class MatchPlayer(Base):
    """Who sat in which finished match: the index for player history and
    head-to-head, so those never scan replay JSON."""

    __tablename__ = "match_players"
    __table_args__ = (Index("match_players_recent", "player_id", desc("finished_at")),)

    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    # No foreign key: archived matches outlive deleted accounts.
    player_id: Mapped[UUID] = mapped_column(primary_key=True)
    seat: Mapped[int]
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
