"""Track the first story clear and awakened character for each season."""

import sqlalchemy as sa
from alembic import op

revision = "20261127_story_progress"
down_revision = "20261127_season_cast"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "season_story_progress",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("clear_game_id", sa.Uuid(), nullable=False),
        sa.Column("awakened_character_id", sa.String(40), nullable=True),
        sa.PrimaryKeyConstraint("season_id", "player_id"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("season_story_progress")
