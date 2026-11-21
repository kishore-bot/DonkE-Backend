"""Player blocks, reports and chat mutes."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_social_safety"
down_revision = "20261121_admin_console"
branch_labels = None
depends_on = None


def player(name: str, **options: object) -> sa.Column:
    return sa.Column(
        name, sa.Uuid(), sa.ForeignKey("players.id", ondelete="CASCADE"), **options
    )


def created() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "player_blocks",
        player("blocker_id", primary_key=True),
        player("blocked_id", primary_key=True),
        created(),
    )
    op.create_index("ix_player_blocks_blocked_id", "player_blocks", ["blocked_id"])
    op.create_table(
        "player_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        player("reporter_id", nullable=False),
        player("target_id", nullable=False),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("status", sa.String(12), server_default="open", nullable=False),
        sa.Column("resolution", sa.String(120), nullable=True),
        created(),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_player_reports_reporter_id", "player_reports", ["reporter_id"])
    op.create_index("ix_player_reports_target_id", "player_reports", ["target_id"])
    op.create_table(
        "player_mutes",
        player("player_id", primary_key=True),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(120), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("player_mutes")
    op.drop_table("player_reports")
    op.drop_table("player_blocks")
