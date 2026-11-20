import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.platform import Base
from app.modules.admin.models import AdminAudit, AdminSession, AdminUser
from app.modules.identity.models import Player, PlayerSession, RefreshToken
from app.modules.matches.models import MatchRecord

# Import the metadata owners so migration drift checks see all tables.
MAPPED_MODELS = (
    AdminAudit,
    AdminSession,
    AdminUser,
    Player,
    PlayerSession,
    RefreshToken,
    MatchRecord,
)


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


settings = Settings()
if settings.postgres_dsn is None:
    raise RuntimeError("Configure DONKE_POSTGRES_DSN before running migrations")
database_url = str(settings.postgres_dsn)
if context.is_offline_mode():
    context.configure(
        url=database_url, target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online(database_url))
