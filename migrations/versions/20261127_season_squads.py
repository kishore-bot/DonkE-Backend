"""Persist frozen season squad rosters and their story clears."""

import sqlalchemy as sa
from alembic import op

revision = "20261127_season_squads"
down_revision = "20261127_match_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "season_squads",
        sa.Column("season_id", sa.Uuid(), primary_key=True),
        sa.Column("party_id", sa.Uuid(), primary_key=True),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.CheckConstraint("target BETWEEN 2 AND 4", name="squad_size"),
    )
    op.create_table(
        "season_squad_members",
        sa.Column("season_id", sa.Uuid(), primary_key=True),
        sa.Column("player_id", sa.Uuid(), primary_key=True),
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("clear_game_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["season_id", "party_id"],
            ["season_squads.season_id", "season_squads.party_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "season_squad_roster", "season_squad_members", ["season_id", "party_id"]
    )


def downgrade() -> None:
    op.drop_table("season_squad_members")
    op.drop_table("season_squads")
