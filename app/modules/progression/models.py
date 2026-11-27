from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Double, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform import Base


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (CheckConstraint("coins >= 0", name="wallet_nonnegative"),)

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    coins: Mapped[int] = mapped_column(server_default="0")


class CoinLedger(Base):
    __tablename__ = "coin_ledger"

    reference: Mapped[str] = mapped_column(String(140), primary_key=True)
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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


class SeasonCharacter(Base):
    __tablename__ = "season_characters"

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    character_id: Mapped[str] = mapped_column(String(40))


class SeasonPlayer(Base):
    __tablename__ = "season_players"

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    points: Mapped[int] = mapped_column(server_default="0")
    bank: Mapped[int] = mapped_column(server_default="0")
    peak_mmr: Mapped[int] = mapped_column(server_default="0")


class SeasonStoryProgress(Base):
    __tablename__ = "season_story_progress"

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    clear_game_id: Mapped[UUID] = mapped_column()
    awakened_character_id: Mapped[str | None] = mapped_column(String(40))


class WeeklyPlayer(Base):
    __tablename__ = "season_weekly"

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    week: Mapped[date] = mapped_column(primary_key=True)
    games: Mapped[int] = mapped_column(server_default="0")
    escapes: Mapped[int] = mapped_column(server_default="0")
    cuts: Mapped[int] = mapped_column(server_default="0")


class Cosmetic(Base):
    __tablename__ = "cosmetics_owned"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    sku: Mapped[str] = mapped_column(String(80), primary_key=True)
    equipped: Mapped[bool] = mapped_column(server_default="false")


class PlayerStats(Base):
    """Lifetime match counters that drive achievements."""

    __tablename__ = "player_stats"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    games: Mapped[int] = mapped_column(server_default="0")
    escapes: Mapped[int] = mapped_column(server_default="0")
    firsts: Mapped[int] = mapped_column(server_default="0")
    donkeys: Mapped[int] = mapped_column(server_default="0")
    cuts_given: Mapped[int] = mapped_column(server_default="0")
    cards_picked: Mapped[int] = mapped_column(server_default="0")
    safe_streak: Mapped[int] = mapped_column(server_default="0")
    best_safe_streak: Mapped[int] = mapped_column(server_default="0")


class Achievement(Base):
    __tablename__ = "player_achievements"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlayerSkill(Base):
    """Hidden Weng-Lin (OpenSkill) rating used for matchmaking only."""

    __tablename__ = "player_skills"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    mu: Mapped[float] = mapped_column(Double, server_default="25.0")
    sigma: Mapped[float] = mapped_column(Double, server_default="8.333333")
    matches: Mapped[int] = mapped_column(server_default="0")


class SeasonDay(Base):
    """Days a player played in a season; five days in a week earns a streak star."""

    __tablename__ = "season_days"

    season_id: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(primary_key=True)
