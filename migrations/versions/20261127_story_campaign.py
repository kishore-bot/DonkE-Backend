"""Persist signed-in story duels, commands and campaign clears."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261127_story_campaign"
down_revision = "20261127_season_squads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_duels",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "season_id",
            sa.Uuid(),
            sa.ForeignKey("seasons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "player_id",
            sa.Uuid(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pin", JSONB(), nullable=False),
        sa.Column("duel", JSONB(), nullable=False),
        sa.Column("finished", sa.Boolean(), nullable=False),
        sa.Column("receipt", JSONB(), nullable=True),
    )
    op.create_index("ix_story_duels_season_id", "story_duels", ["season_id"])
    op.create_index("ix_story_duels_expires_at", "story_duels", ["expires_at"])
    op.create_index(
        "story_duels_player_recent",
        "story_duels",
        ["player_id", sa.text("created_at DESC")],
    )
    op.create_table(
        "story_duel_commands",
        sa.Column(
            "duel_id",
            sa.Uuid(),
            sa.ForeignKey("story_duels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("command", JSONB(), nullable=False),
        sa.Column("update", JSONB(), nullable=False),
    )
    op.create_table(
        "season_chapter_clears",
        sa.Column(
            "season_id",
            sa.Uuid(),
            sa.ForeignKey("seasons.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "player_id",
            sa.Uuid(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chapter_id", sa.String(40), primary_key=True),
        sa.Column("game_id", sa.Uuid(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("season_chapter_clears")
    op.drop_table("story_duel_commands")
    op.drop_table("story_duels")
