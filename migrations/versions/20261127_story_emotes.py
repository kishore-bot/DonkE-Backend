"""Store seasonal emote selection and analysed story highlights."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261127_story_emotes"
down_revision = "20261127_story_campaign"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "season_emotes",
        sa.Column(
            "season_id",
            sa.Uuid(),
            sa.ForeignKey("seasons.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("player_id", sa.Uuid(), primary_key=True),
        sa.Column("sku", sa.String(80), nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id", "sku"],
            ["cosmetics_owned.player_id", "cosmetics_owned.sku"],
            ondelete="CASCADE",
        ),
    )
    op.add_column("story_duels", sa.Column("highlight", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("story_duels", "highlight")
    op.drop_table("season_emotes")
