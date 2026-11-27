from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform import Base
from app.modules.story.lines import Moment


class SeasonCue(Base):
    __tablename__ = "season_cues"
    __table_args__ = (
        UniqueConstraint(
            "pack_key", "character_id", "moment", name="season_cue_identity"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pack_key: Mapped[str] = mapped_column(String(80))
    character_id: Mapped[str] = mapped_column(String(40))
    moment: Mapped[Moment] = mapped_column(String(12))
    stage: Mapped[str] = mapped_column(String(12), default="english")
    en: Mapped[str | None] = mapped_column(String(180))
    ja: Mapped[str | None] = mapped_column(String(180))
    en_source: Mapped[str | None] = mapped_column(String(8))
    ja_source: Mapped[str | None] = mapped_column(String(8))


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
