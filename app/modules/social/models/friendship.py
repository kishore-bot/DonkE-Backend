from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Friendship(Base):
    __tablename__ = "friendships"
    __table_args__ = (CheckConstraint("first_id < second_id", name="friendship_order"),)

    first_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    second_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    requester_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE")
    )
    accepted: Mapped[bool] = mapped_column(server_default="false")
