from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.core.database import Base
from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.admin.models import AdminAudit, AdminSession, AdminUser, RuntimeFlag
from app.modules.ai.models import (
    FairPlayCase,
    MatchAnalysis,
    PlayerRival,
    RuleEmbedding,
)
from app.modules.game.models import StoryDuel, StoryDuelCommand, StoryRivalMemory
from app.modules.identity.models import Player, PlayerSession, RefreshToken
from app.modules.matches.models import MatchPlayer, MatchRecord
from app.modules.progression.models import (
    Achievement,
    CoinLedger,
    Cosmetic,
    PlayerSkill,
    PlayerStats,
    Season,
    SeasonChapterClear,
    SeasonCharacter,
    SeasonDay,
    SeasonEmote,
    SeasonPlayer,
    SeasonSquad,
    SeasonSquadMember,
    SeasonStoryProgress,
    Wallet,
    WeeklyPlayer,
)
from app.modules.social.models import (
    Friendship,
    Party,
    PartyInvite,
    PartyMember,
    PlayerBlock,
    PlayerMute,
    PlayerReport,
)
from app.modules.story.models import SeasonCue, SeasonMedia

# Register the complete schema for Alembic and readiness.
MAPPED_MODELS = (
    AdminAudit,
    AdminSession,
    AdminUser,
    Player,
    PlayerSession,
    RefreshToken,
    MatchRecord,
    MatchPlayer,
    StoryDuel,
    StoryDuelCommand,
    StoryRivalMemory,
    CoinLedger,
    Cosmetic,
    Season,
    SeasonCharacter,
    SeasonChapterClear,
    SeasonPlayer,
    SeasonSquad,
    SeasonSquadMember,
    SeasonStoryProgress,
    Wallet,
    WeeklyPlayer,
    PlayerStats,
    Achievement,
    PlayerSkill,
    SeasonDay,
    SeasonEmote,
    MatchAnalysis,
    PlayerRival,
    FairPlayCase,
    RuntimeFlag,
    PlayerBlock,
    PlayerReport,
    PlayerMute,
    Friendship,
    Party,
    PartyInvite,
    PartyMember,
    RuleEmbedding,
    SeasonCue,
    SeasonMedia,
)


def has_required_schema(connection: Connection) -> bool:
    tables = Base.metadata.sorted_tables
    reflected = inspect(connection).get_multi_columns(
        filter_names=[table.name for table in tables]
    )
    for table in tables:
        columns = reflected.get((table.schema, table.name), [])
        expected = {
            column.name: (
                column.type.compile(dialect=connection.dialect),
                column.nullable,
            )
            for column in table.columns
        }
        actual = {
            column["name"]: (
                column["type"].compile(dialect=connection.dialect),
                column["nullable"],
            )
            for column in columns
        }
        if not expected.items() <= actual.items():
            return False
        for column in columns:
            if (
                column["name"] not in expected
                and not column["nullable"]
                and column.get("default") is None
                and column.get("identity") is None
                and column.get("computed") is None
            ):
                return False
    return bool(connection.scalar(text("SELECT to_regtype('vector') IS NOT NULL")))


async def check_storage_ready(platform: Platform) -> None:
    async with platform.engine.connect() as connection:
        if not await connection.run_sync(has_required_schema):
            raise AppError(
                503,
                "schema_mismatch",
                "Online storage does not have the required tables and pgvector",
            )
    await platform.redis.ping()
