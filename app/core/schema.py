from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.core.database import Base
from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.admin.models.admin_audit import AdminAudit
from app.modules.admin.models.admin_session import AdminSession
from app.modules.admin.models.admin_user import AdminUser
from app.modules.admin.models.runtime_flag import RuntimeFlag
from app.modules.ai.models.fair_play_case import FairPlayCase
from app.modules.ai.models.match_analysis import MatchAnalysis
from app.modules.ai.models.player_rival import PlayerRival
from app.modules.ai.models.rule_embedding import RuleEmbedding
from app.modules.game.models.story_duel import StoryDuel
from app.modules.game.models.story_duel_command import StoryDuelCommand
from app.modules.game.models.story_rival_memory import StoryRivalMemory
from app.modules.identity.models.player import Player
from app.modules.identity.models.player_session import PlayerSession
from app.modules.identity.models.refresh_token import RefreshToken
from app.modules.matches.models.match_player import MatchPlayer
from app.modules.matches.models.match_record import MatchRecord
from app.modules.progression.models.achievement import Achievement
from app.modules.progression.models.coin_ledger import CoinLedger
from app.modules.progression.models.cosmetic import Cosmetic
from app.modules.progression.models.player_skill import PlayerSkill
from app.modules.progression.models.player_stats import PlayerStats
from app.modules.progression.models.season import Season
from app.modules.progression.models.season_chapter_clear import SeasonChapterClear
from app.modules.progression.models.season_character import SeasonCharacter
from app.modules.progression.models.season_day import SeasonDay
from app.modules.progression.models.season_emote import SeasonEmote
from app.modules.progression.models.season_player import SeasonPlayer
from app.modules.progression.models.season_squad import SeasonSquad
from app.modules.progression.models.season_squad_member import SeasonSquadMember
from app.modules.progression.models.season_story_progress import SeasonStoryProgress
from app.modules.progression.models.wallet import Wallet
from app.modules.progression.models.weekly_player import WeeklyPlayer
from app.modules.social.models.friendship import Friendship
from app.modules.social.models.party import Party
from app.modules.social.models.party_invite import PartyInvite
from app.modules.social.models.party_member import PartyMember
from app.modules.social.models.player_block import PlayerBlock
from app.modules.social.models.player_mute import PlayerMute
from app.modules.social.models.player_report import PlayerReport
from app.modules.story.models.season_cue import SeasonCue
from app.modules.story.models.season_media import SeasonMedia

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
