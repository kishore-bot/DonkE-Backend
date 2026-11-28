from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    theme: Mapped[str] = mapped_column(String(60))
    pack_key: Mapped[str | None] = mapped_column(String(80))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Recorded at close: False when a later season had already started, so
    # the soft MMR reset was skipped. Stored so repeat closes answer the same.
    ratings_reset: Mapped[bool | None]
