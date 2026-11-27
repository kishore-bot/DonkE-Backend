from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Friendship(Base):
    __tablename__ = "friendships"
    __table_args__ = (CheckConstraint("first_id < second_id", name="friendship_order"),)

    first_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    second_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    requester_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE")
    )
    accepted: Mapped[bool] = mapped_column(server_default="false")


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    leader_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE")
    )


class PartyMember(Base):
    __tablename__ = "party_members"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    party_id: Mapped[UUID] = mapped_column(
        ForeignKey("parties.id", ondelete="CASCADE"), index=True
    )


class PartyInvite(Base):
    __tablename__ = "party_invites"

    party_id: Mapped[UUID] = mapped_column(
        ForeignKey("parties.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class PlayerBlock(Base):
    """`blocker_id` never sees, hears from or gets invites from `blocked_id`."""

    __tablename__ = "player_blocks"

    blocker_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    blocked_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlayerReport(Base):
    __tablename__ = "player_reports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reporter_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(20))
    game_id: Mapped[UUID | None]
    note: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), server_default="open")
    resolution: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlayerMute(Base):
    """A chat mute set by a moderator; the player can still play."""

    __tablename__ = "player_mutes"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(120))
