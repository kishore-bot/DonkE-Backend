"""Index finished matches by player, and matches by finish time.

Player history and head-to-head used to scan every replay's JSON. The
match_players table is backfilled from existing replays in one statement.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261121_match_players"
down_revision = "20261121_seal_totp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_matches_finished_at", "matches", ["finished_at"])
    op.create_table(
        "match_players",
        sa.Column(
            "game_id",
            sa.Uuid(),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("player_id", sa.Uuid(), primary_key=True),
        sa.Column("seat", sa.Integer(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "match_players_recent",
        "match_players",
        ["player_id", sa.text("finished_at DESC")],
    )
    op.execute(
        """
        INSERT INTO match_players (game_id, player_id, seat, finished_at)
        SELECT m.id, (seat.value ->> 'player_id')::uuid, seat.ordinality - 1,
               m.finished_at
        FROM matches AS m,
             jsonb_array_elements(m.replay -> 'seats') WITH ORDINALITY AS seat
        WHERE seat.value ->> 'player_id' IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("match_players_recent", table_name="match_players")
    op.drop_table("match_players")
    op.drop_index("ix_matches_finished_at", table_name="matches")
