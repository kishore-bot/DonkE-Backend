from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SeasonMedia(Base):
    __tablename__ = "season_media"
    __table_args__ = (
        Index("season_media_slot", "pack_key", "character_id", "slot", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    pack_key: Mapped[str] = mapped_column(String(80))
    character_id: Mapped[str] = mapped_column(String(40))
    slot: Mapped[str] = mapped_column(String(24))
    object_key: Mapped[str] = mapped_column(String(220), unique=True)
    bytes: Mapped[int]
    content_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
