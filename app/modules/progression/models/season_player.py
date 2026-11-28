from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SeasonPlayer(Base):
    __tablename__ = "season_players"

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    points: Mapped[int] = mapped_column(server_default="0")
    bank: Mapped[int] = mapped_column(server_default="0")
    peak_mmr: Mapped[int] = mapped_column(server_default="0")
