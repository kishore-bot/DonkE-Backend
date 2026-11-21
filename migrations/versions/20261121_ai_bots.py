"""Rival records and fair-play cases."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261121_ai_bots"
down_revision = "20261121_ai_coaching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_rivals",
        sa.Column(
            "player_id",
            sa.Uuid(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("persona", sa.String(20), nullable=False),
        *(
            sa.Column(name, sa.Integer(), server_default="0", nullable=False)
            for name in ("games", "wins", "losses")
        ),
    )
    op.create_table(
        "fair_play_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "player_id",
            sa.Uuid(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(12), server_default="open", nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("stats", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_fair_play_cases_player_id", "fair_play_cases", ["player_id"])
    op.create_index(
        "fair_play_one_open",
        "fair_play_cases",
        ["player_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_table("fair_play_cases")
    op.drop_table("player_rivals")
