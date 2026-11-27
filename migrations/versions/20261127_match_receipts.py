"""Store settled reward receipts for each match participant."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261127_match_receipts"
down_revision = "20261127_season_cues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("match_players", sa.Column("receipt", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("match_players", "receipt")
