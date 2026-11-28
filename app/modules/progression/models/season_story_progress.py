from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SeasonStoryProgress(Base):
    __tablename__ = "season_story_progress"

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    clear_game_id: Mapped[UUID] = mapped_column()
    awakened_character_id: Mapped[str | None] = mapped_column(String(40))
