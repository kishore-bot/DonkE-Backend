"""Add lifetime stats, achievements, hidden skill and season play days."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_progression_plus"
down_revision = "20261120_ai"
branch_labels = None
depends_on = None


def player_fk() -> sa.ForeignKey:
    return sa.ForeignKey("players.id", ondelete="CASCADE")


def counter(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), server_default="0", nullable=False)


def upgrade() -> None:
    op.create_table(
        "player_stats",
        sa.Column("player_id", sa.Uuid(), player_fk(), primary_key=True),
        *(
            counter(name)
            for name in (
                "games",
                "escapes",
                "firsts",
                "donkeys",
                "cuts_given",
                "cards_picked",
                "safe_streak",
                "best_safe_streak",
            )
        ),
    )
    op.create_table(
        "player_achievements",
        sa.Column("player_id", sa.Uuid(), player_fk(), primary_key=True),
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column(
            "unlocked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "player_skills",
        sa.Column("player_id", sa.Uuid(), player_fk(), primary_key=True),
        sa.Column("mu", sa.Double(), server_default="25.0", nullable=False),
        sa.Column("sigma", sa.Double(), server_default="8.333333", nullable=False),
        counter("matches"),
    )
    op.create_table(
        "season_days",
        sa.Column(
            "season_id",
            sa.Uuid(),
            sa.ForeignKey("seasons.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("player_id", sa.Uuid(), player_fk(), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("season_days")
    op.drop_table("player_skills")
    op.drop_table("player_achievements")
    op.drop_table("player_stats")
