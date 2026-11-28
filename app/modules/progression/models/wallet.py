from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (CheckConstraint("coins >= 0", name="wallet_nonnegative"),)

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    coins: Mapped[int] = mapped_column(server_default="0")
