"""Add season pack references and player character selections."""

import sqlalchemy as sa
from alembic import op

revision = "20261127_season_cast"
down_revision = "20261121_season_reset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("seasons", sa.Column("pack_key", sa.String(80), nullable=True))
    op.create_table(
        "season_characters",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("season_id", "player_id"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("season_characters")
    op.drop_column("seasons", "pack_key")
