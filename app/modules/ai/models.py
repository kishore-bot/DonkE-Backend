from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Double,
    ForeignKey,
    Index,
    String,
    desc,
    func,
    text,
)
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


class FairPlayCase(Base):
    __tablename__ = "fair_play_cases"
    __table_args__ = (
        Index(
            "fair_play_one_open",
            "player_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(12), server_default="open")
    score: Mapped[int]
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RuleEmbedding(Base):
    __tablename__ = "rule_embeddings"

    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    model: Mapped[str] = mapped_column(String(120))
    vector_json: Mapped[str]


class PlayerRival(Base):
    __tablename__ = "player_rivals"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    persona: Mapped[str] = mapped_column(String(20))
    games: Mapped[int] = mapped_column(server_default="0")
    wins: Mapped[int] = mapped_column(server_default="0")
    losses: Mapped[int] = mapped_column(server_default="0")
