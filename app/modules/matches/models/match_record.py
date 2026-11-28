from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MatchRecord(Base):
    __tablename__ = "matches"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    replay: Mapped[dict[str, Any]] = mapped_column(JSONB)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
