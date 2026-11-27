"""Season media and rival memory

Revision ID: 0002_season_expansion
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_season_expansion"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "season_media",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pack_key", sa.String(length=80), nullable=False),
        sa.Column("character_id", sa.String(length=40), nullable=False),
        sa.Column("slot", sa.String(length=24), nullable=False),
        sa.Column("object_key", sa.String(length=220), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index(
        "season_media_slot",
        "season_media",
        ["pack_key", "character_id", "slot", "published_at"],
        unique=False,
    )
    op.create_table(
        "story_rival_memory",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.String(length=40), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("moment", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("season_id", "player_id", "chapter_id"),
    )


def downgrade() -> None:
    op.drop_table("story_rival_memory")
    op.drop_index("season_media_slot", table_name="season_media")
    op.drop_table("season_media")
