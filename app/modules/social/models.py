from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform import Base


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
