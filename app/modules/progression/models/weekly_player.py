from datetime import date
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WeeklyPlayer(Base):
    __tablename__ = "season_weekly"

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    week: Mapped[date] = mapped_column(primary_key=True)
    games: Mapped[int] = mapped_column(server_default="0")
    escapes: Mapped[int] = mapped_column(server_default="0")
    cuts: Mapped[int] = mapped_column(server_default="0")
