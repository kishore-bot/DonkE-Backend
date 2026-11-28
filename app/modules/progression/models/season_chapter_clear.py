from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SeasonChapterClear(Base):
    __tablename__ = "season_chapter_clears"

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    chapter_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    game_id: Mapped[UUID]
