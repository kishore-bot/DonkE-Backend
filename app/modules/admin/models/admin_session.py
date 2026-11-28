from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    admin_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
