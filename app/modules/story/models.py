from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform import Base


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
    moment: Mapped[Literal["strike", "victory"]] = mapped_column(String(12))
    stage: Mapped[str] = mapped_column(String(12), default="english")
    en: Mapped[str | None] = mapped_column(String(180))
    ja: Mapped[str | None] = mapped_column(String(180))
    en_source: Mapped[str | None] = mapped_column(String(8))
    ja_source: Mapped[str | None] = mapped_column(String(8))
