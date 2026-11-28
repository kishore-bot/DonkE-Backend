from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StoryDuelCommand(Base):
    __tablename__ = "story_duel_commands"

    duel_id: Mapped[UUID] = mapped_column(
        ForeignKey("story_duels.id", ondelete="CASCADE"), primary_key=True
    )
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    command: Mapped[dict] = mapped_column(JSONB)
    update: Mapped[dict] = mapped_column(JSONB)
