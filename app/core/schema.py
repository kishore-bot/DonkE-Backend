from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from app.core.platform import Base
from app.modules.admin.flags import RuntimeFlag
from app.modules.admin.models import AdminAudit, AdminSession, AdminUser
from app.modules.ai.coaching import MatchAnalysis
from app.modules.ai.fair_play import FairPlayCase
from app.modules.ai.index import RuleEmbedding
from app.modules.ai.rivals import PlayerRival
from app.modules.identity.models import Player, PlayerSession, RefreshToken
from app.modules.matches.models import MatchPlayer, MatchRecord
from app.modules.progression.models import (
    Achievement,
    CoinLedger,
    Cosmetic,
    PlayerSkill,
    PlayerStats,
    Season,
    SeasonDay,
    SeasonPlayer,
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

# Import all mapped tables for both migration drift checks and startup on an expanded schema.
MAPPED_MODELS = (
    AdminAudit,
    AdminSession,
    AdminUser,
    Player,
    PlayerSession,
    RefreshToken,
    MatchRecord,
    MatchPlayer,
    CoinLedger,
    Cosmetic,
    Season,
    SeasonPlayer,
    Wallet,
    WeeklyPlayer,
    PlayerStats,
    Achievement,
    PlayerSkill,
    SeasonDay,
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
    return True
