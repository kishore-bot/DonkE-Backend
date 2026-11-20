from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('viewer', 'moderator', 'admin')", name="admin_user_role"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(48), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    admin_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AdminAudit(Base):
    __tablename__ = "admin_audit"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    admin_id: Mapped[UUID] = mapped_column(ForeignKey("admin_users.id"), index=True)
    action: Mapped[str] = mapped_column(String(48))
    reason: Mapped[str] = mapped_column(String(120))
    request_id: Mapped[UUID]
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
