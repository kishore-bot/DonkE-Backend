"""Create the online platform and identity schema."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_platform"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "players",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("google_sub", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(40), nullable=False),
        sa.Column("language", sa.String(2), nullable=False, server_default="ml"),
        sa.Column("mmr", sa.Integer(), nullable=False, server_default="1200"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "player_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "player_id",
            sa.Uuid(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_player_sessions_player_id", "player_sessions", ["player_id"])
    op.create_index("ix_player_sessions_expires_at", "player_sessions", ["expires_at"])
    op.create_table(
        "refresh_tokens",
        sa.Column("digest", sa.LargeBinary(32), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("player_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(48), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "role IN ('viewer', 'moderator', 'admin')", name="admin_user_role"
        ),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("token_digest", sa.LargeBinary(32), primary_key=True),
        sa.Column(
            "admin_id",
            sa.Uuid(),
            sa.ForeignKey("admin_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_sessions_admin_id", "admin_sessions", ["admin_id"])
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])
    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "admin_id", sa.Uuid(), sa.ForeignKey("admin_users.id"), nullable=False
        ),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("reason", sa.String(120), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_admin_audit_admin_id", "admin_audit", ["admin_id"])


def downgrade() -> None:
    for table in (
        "admin_audit",
        "admin_sessions",
        "admin_users",
        "refresh_tokens",
        "player_sessions",
        "players",
    ):
        op.drop_table(table)
