"""Persist reviewed bilingual cue workflows."""

import sqlalchemy as sa
from alembic import op

revision = "20261127_season_cues"
down_revision = "20261127_story_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "season_cues",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("pack_key", sa.String(80), nullable=False),
        sa.Column("character_id", sa.String(40), nullable=False),
        sa.Column("moment", sa.String(12), nullable=False),
        sa.Column("stage", sa.String(12), nullable=False),
        sa.Column("en", sa.String(180), nullable=True),
        sa.Column("ja", sa.String(180), nullable=True),
        sa.Column("en_source", sa.String(8), nullable=True),
        sa.Column("ja_source", sa.String(8), nullable=True),
        sa.UniqueConstraint(
            "pack_key", "character_id", "moment", name="season_cue_identity"
        ),
    )


def downgrade() -> None:
    op.drop_table("season_cues")
