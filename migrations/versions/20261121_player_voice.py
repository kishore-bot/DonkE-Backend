"""Player's chosen commentary voice."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_player_voice"
down_revision = "20261121_social_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("players", sa.Column("voice", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("players", "voice")
