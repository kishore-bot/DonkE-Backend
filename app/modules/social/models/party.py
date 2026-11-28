from uuid import UUID, uuid4

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    leader_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE")
    )
