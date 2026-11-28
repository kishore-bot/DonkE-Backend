from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Cosmetic(Base):
    __tablename__ = "cosmetics_owned"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    sku: Mapped[str] = mapped_column(String(80), primary_key=True)
    equipped: Mapped[bool] = mapped_column(server_default="false")
