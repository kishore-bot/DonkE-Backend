from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SeasonSquad(Base):
    __tablename__ = "season_squads"
    __table_args__ = (CheckConstraint("target BETWEEN 2 AND 4", name="squad_size"),)

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    # Persist the enrollment after the live party is deleted.
    party_id: Mapped[UUID] = mapped_column(primary_key=True)
    target: Mapped[int]
