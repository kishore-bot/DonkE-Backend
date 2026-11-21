"""Admin two-factor sign-in and runtime flags."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261121_admin_console"
down_revision = "20261121_ai_bots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_users", sa.Column("totp_secret", sa.String(64), nullable=True))
    op.add_column(
        "admin_users",
        sa.Column("totp_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_table(
        "runtime_flags",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("runtime_flags")
    op.drop_column("admin_users", "totp_enabled")
    op.drop_column("admin_users", "totp_secret")
