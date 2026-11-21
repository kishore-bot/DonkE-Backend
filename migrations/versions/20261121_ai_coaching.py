"""Store engine analyses of finished matches for coaching and insights."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261121_ai_coaching"
down_revision = "20261121_progression_plus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "match_analyses",
        sa.Column(
            "game_id",
            sa.Uuid(),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "player_id",
            sa.Uuid(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("decisions", sa.Integer(), nullable=False),
        sa.Column("accuracy", sa.Double(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "match_analyses_player_recent",
        "match_analyses",
        ["player_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("match_analyses_player_recent", table_name="match_analyses")
    op.drop_table("match_analyses")
