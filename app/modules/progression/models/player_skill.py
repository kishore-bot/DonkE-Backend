from uuid import UUID

from sqlalchemy import Double, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlayerSkill(Base):
    """Hidden Weng-Lin (OpenSkill) rating used for matchmaking only."""

    __tablename__ = "player_skills"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    mu: Mapped[float] = mapped_column(Double, server_default="25.0")
    sigma: Mapped[float] = mapped_column(Double, server_default="8.333333")
    matches: Mapped[int] = mapped_column(server_default="0")
