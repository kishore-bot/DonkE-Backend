from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PartyMember(Base):
    __tablename__ = "party_members"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    party_id: Mapped[UUID] = mapped_column(
        ForeignKey("parties.id", ondelete="CASCADE"), index=True
    )
