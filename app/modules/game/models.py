from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, desc
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform import Base


class StoryDuel(Base):
    __tablename__ = "story_duels"
    __table_args__ = (
        Index("story_duels_player_recent", "player_id", desc("created_at")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), index=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    pin: Mapped[dict] = mapped_column(JSONB)
    duel: Mapped[dict] = mapped_column(JSONB)
    finished: Mapped[bool]
    receipt: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    highlight: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class StoryDuelCommand(Base):
    __tablename__ = "story_duel_commands"

    duel_id: Mapped[UUID] = mapped_column(
        ForeignKey("story_duels.id", ondelete="CASCADE"), primary_key=True
    )
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    command: Mapped[dict] = mapped_column(JSONB)
    update: Mapped[dict] = mapped_column(JSONB)
