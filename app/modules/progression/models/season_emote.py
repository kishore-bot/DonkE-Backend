from uuid import UUID

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SeasonEmote(Base):
    __tablename__ = "season_emotes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["player_id", "sku"],
            ["cosmetics_owned.player_id", "cosmetics_owned.sku"],
            ondelete="CASCADE",
        ),
    )

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(80))
