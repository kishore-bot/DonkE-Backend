"""Add curated rule embeddings."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_ai"
down_revision = "20261120_progression"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_embeddings",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("vector_json", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rule_embeddings")
