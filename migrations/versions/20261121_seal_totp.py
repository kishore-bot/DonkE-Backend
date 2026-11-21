"""Encrypt admin TOTP secrets at rest.

Widens the column for the sealed form and seals any secret still stored in
plain text, using the same key the app uses (DONKE_ADMIN_TOTP_KEY, or one
derived from DONKE_AUTH_SECRET).
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import Settings
from app.modules.admin import vault

revision = "20261121_seal_totp"
down_revision = "20261121_player_voice"
branch_labels = None
depends_on = None

users = sa.table(
    "admin_users",
    sa.column("id", sa.Uuid()),
    sa.column("totp_secret", sa.String()),
)


def upgrade() -> None:
    op.alter_column(
        "admin_users",
        "totp_secret",
        type_=sa.String(128),
        existing_type=sa.String(64),
        existing_nullable=True,
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(users.c.id, users.c.totp_secret).where(
            users.c.totp_secret.is_not(None)
        )
    ).all()
    plain = [
        (row.id, row.totp_secret)
        for row in rows
        if not vault.is_sealed(row.totp_secret)
    ]
    if not plain:
        return
    settings = Settings()
    for admin_id, secret in plain:
        connection.execute(
            sa.update(users)
            .where(users.c.id == admin_id)
            .values(totp_secret=vault.seal(settings, admin_id, secret))
        )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(users.c.id, users.c.totp_secret).where(
            users.c.totp_secret.is_not(None)
        )
    ).all()
    settings = Settings()
    for row in rows:
        if vault.is_sealed(row.totp_secret):
            connection.execute(
                sa.update(users)
                .where(users.c.id == row.id)
                .values(totp_secret=vault.unseal(settings, row.id, row.totp_secret))
            )
    op.alter_column(
        "admin_users",
        "totp_secret",
        type_=sa.String(64),
        existing_type=sa.String(128),
        existing_nullable=True,
    )
