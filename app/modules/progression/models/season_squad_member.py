from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SeasonSquadMember(Base):
    __tablename__ = "season_squad_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["season_id", "party_id"],
            ["season_squads.season_id", "season_squads.party_id"],
            ondelete="CASCADE",
        ),
        Index("season_squad_roster", "season_id", "party_id"),
    )

    season_id: Mapped[UUID] = mapped_column(primary_key=True)
    player_id: Mapped[UUID] = mapped_column(primary_key=True)
    party_id: Mapped[UUID]
    clear_game_id: Mapped[UUID | None]
