from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlayerRival(Base):
    __tablename__ = "player_rivals"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    persona: Mapped[str] = mapped_column(String(20))
    games: Mapped[int] = mapped_column(server_default="0")
    wins: Mapped[int] = mapped_column(server_default="0")
    losses: Mapped[int] = mapped_column(server_default="0")
