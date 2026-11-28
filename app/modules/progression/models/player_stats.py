from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlayerStats(Base):
    """Lifetime match counters that drive achievements."""

    __tablename__ = "player_stats"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    games: Mapped[int] = mapped_column(server_default="0")
    escapes: Mapped[int] = mapped_column(server_default="0")
    firsts: Mapped[int] = mapped_column(server_default="0")
    donkeys: Mapped[int] = mapped_column(server_default="0")
    cuts_given: Mapped[int] = mapped_column(server_default="0")
    cards_picked: Mapped[int] = mapped_column(server_default="0")
    safe_streak: Mapped[int] = mapped_column(server_default="0")
    best_safe_streak: Mapped[int] = mapped_column(server_default="0")
