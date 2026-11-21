"""Record whether closing a season applied the soft MMR reset."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_season_reset"
down_revision = "20261121_match_players"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("seasons", sa.Column("ratings_reset", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("seasons", "ratings_reset")
