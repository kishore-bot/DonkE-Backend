"""Initial DonkE schema

Revision ID: 0001_initial
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "admin_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=48), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totp_secret", sa.String(length=128), nullable=True),
        sa.Column("totp_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint(
            "role IN ('viewer', 'moderator', 'admin')", name="admin_user_role"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("replay", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_matches_finished_at"), "matches", ["finished_at"], unique=False
    )
    op.create_table(
        "players",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("google_sub", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=40), nullable=False),
        sa.Column("language", sa.String(length=2), server_default="ml", nullable=False),
        sa.Column("mmr", sa.Integer(), server_default="1200", nullable=False),
        sa.Column("voice", sa.String(length=20), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("google_sub"),
    )
    op.create_table(
        "rule_embeddings",
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("vector_json", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("source"),
    )
    op.create_table(
        "runtime_flags",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "season_cues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pack_key", sa.String(length=80), nullable=False),
        sa.Column("character_id", sa.String(length=40), nullable=False),
        sa.Column("moment", sa.String(length=12), nullable=False),
        sa.Column("stage", sa.String(length=12), nullable=False),
        sa.Column("en", sa.String(length=180), nullable=True),
        sa.Column("ja", sa.String(length=180), nullable=True),
        sa.Column("en_source", sa.String(length=8), nullable=True),
        sa.Column("ja_source", sa.String(length=8), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pack_key", "character_id", "moment", name="season_cue_identity"
        ),
    )
    op.create_table(
        "seasons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("theme", sa.String(length=60), nullable=False),
        sa.Column("pack_key", sa.String(length=80), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ratings_reset", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("reason", sa.String(length=120), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_audit_admin_id"), "admin_audit", ["admin_id"], unique=False
    )
    op.create_table(
        "admin_sessions",
        sa.Column("token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admin_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_digest"),
    )
    op.create_index(
        op.f("ix_admin_sessions_admin_id"), "admin_sessions", ["admin_id"], unique=False
    )
    op.create_index(
        op.f("ix_admin_sessions_expires_at"),
        "admin_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "coin_ledger",
        sa.Column("reference", sa.String(length=140), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("reference"),
    )
    op.create_index(
        op.f("ix_coin_ledger_player_id"), "coin_ledger", ["player_id"], unique=False
    )
    op.create_table(
        "cosmetics_owned",
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("equipped", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("player_id", "sku"),
    )
    op.create_table(
        "fair_play_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=12), server_default="open", nullable=False
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "fair_play_one_open",
        "fair_play_cases",
        ["player_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        op.f("ix_fair_play_cases_player_id"),
        "fair_play_cases",
        ["player_id"],
        unique=False,
    )
    op.create_table(
        "friendships",
        sa.Column("first_id", sa.Uuid(), nullable=False),
        sa.Column("second_id", sa.Uuid(), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("accepted", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint("first_id < second_id", name="friendship_order"),
        sa.ForeignKeyConstraint(["first_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["second_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("first_id", "second_id"),
    )
    op.create_index(
        op.f("ix_friendships_second_id"), "friendships", ["second_id"], unique=False
    )
    op.create_table(
        "match_analyses",
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("decisions", sa.Integer(), nullable=False),
        sa.Column("accuracy", sa.Double(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["game_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("game_id", "player_id"),
    )
    op.create_index(
        "match_analyses_player_recent",
        "match_analyses",
        ["player_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "match_players",
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("seat", sa.Integer(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "receipt",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["game_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("game_id", "player_id"),
    )
    op.create_index(
        "match_players_recent",
        "match_players",
        ["player_id", sa.literal_column("finished_at DESC")],
        unique=False,
    )
    op.create_table(
        "parties",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("leader_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["leader_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "player_achievements",
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column(
            "unlocked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("player_id", "key"),
    )
    op.create_table(
        "player_blocks",
        sa.Column("blocker_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blocked_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocker_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("blocker_id", "blocked_id"),
    )
    op.create_index(
        op.f("ix_player_blocks_blocked_id"),
        "player_blocks",
        ["blocked_id"],
        unique=False,
    )
    op.create_table(
        "player_mutes",
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("player_id"),
    )
    op.create_table(
        "player_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column(
            "status", sa.String(length=12), server_default="open", nullable=False
        ),
        sa.Column("resolution", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["reporter_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_player_reports_reporter_id"),
        "player_reports",
        ["reporter_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_player_reports_target_id"),
        "player_reports",
        ["target_id"],
        unique=False,
    )
    op.create_table(
        "player_rivals",
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("persona", sa.String(length=20), nullable=False),
        sa.Column("games", sa.Integer(), server_default="0", nullable=False),
        sa.Column("wins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("losses", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("player_id"),
    )
    op.create_table(
        "player_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_player_sessions_expires_at"),
        "player_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_player_sessions_player_id"),
        "player_sessions",
        ["player_id"],
        unique=False,
    )
    op.create_table(
        "player_skills",
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("mu", sa.Double(), server_default="25.0", nullable=False),
        sa.Column("sigma", sa.Double(), server_default="8.333333", nullable=False),
        sa.Column("matches", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("player_id"),
    )
    op.create_table(
        "player_stats",
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("games", sa.Integer(), server_default="0", nullable=False),
        sa.Column("escapes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("firsts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("donkeys", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cuts_given", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cards_picked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("safe_streak", sa.Integer(), server_default="0", nullable=False),
        sa.Column("best_safe_streak", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("player_id"),
    )
    op.create_table(
        "season_chapter_clears",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.String(length=40), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("season_id", "player_id", "chapter_id"),
    )
    op.create_table(
        "season_characters",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("season_id", "player_id"),
    )
    op.create_table(
        "season_days",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("season_id", "player_id", "day"),
    )
    op.create_table(
        "season_players",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("points", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bank", sa.Integer(), server_default="0", nullable=False),
        sa.Column("peak_mmr", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("season_id", "player_id"),
    )
    op.create_table(
        "season_squads",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.CheckConstraint("target BETWEEN 2 AND 4", name="squad_size"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("season_id", "party_id"),
    )
    op.create_table(
        "season_story_progress",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("clear_game_id", sa.Uuid(), nullable=False),
        sa.Column("awakened_character_id", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("season_id", "player_id"),
    )
    op.create_table(
        "season_weekly",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("week", sa.Date(), nullable=False),
        sa.Column("games", sa.Integer(), server_default="0", nullable=False),
        sa.Column("escapes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cuts", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("season_id", "player_id", "week"),
    )
    op.create_table(
        "story_duels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pin", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duel", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("finished", sa.Boolean(), nullable=False),
        sa.Column(
            "receipt",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "highlight",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_story_duels_expires_at"), "story_duels", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_story_duels_season_id"), "story_duels", ["season_id"], unique=False
    )
    op.create_index(
        "story_duels_player_recent",
        "story_duels",
        ["player_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "wallets",
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("coins", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("coins >= 0", name="wallet_nonnegative"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("player_id"),
    )
    op.create_table(
        "party_invites",
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("party_id", "player_id"),
    )
    op.create_index(
        op.f("ix_party_invites_player_id"), "party_invites", ["player_id"], unique=False
    )
    op.create_table(
        "party_members",
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("player_id"),
    )
    op.create_index(
        op.f("ix_party_members_party_id"), "party_members", ["party_id"], unique=False
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["player_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("digest"),
    )
    op.create_index(
        op.f("ix_refresh_tokens_session_id"),
        "refresh_tokens",
        ["session_id"],
        unique=False,
    )
    op.create_table(
        "season_emotes",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id", "sku"],
            ["cosmetics_owned.player_id", "cosmetics_owned.sku"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("season_id", "player_id"),
    )
    op.create_table(
        "season_squad_members",
        sa.Column("season_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("clear_game_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["season_id", "party_id"],
            ["season_squads.season_id", "season_squads.party_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("season_id", "player_id"),
    )
    op.create_index(
        "season_squad_roster",
        "season_squad_members",
        ["season_id", "party_id"],
        unique=False,
    )
    op.create_table(
        "story_duel_commands",
        sa.Column("duel_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("command", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("update", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["duel_id"], ["story_duels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("duel_id", "request_id"),
    )


def downgrade() -> None:
    # The database can share pgvector with other applications.
    op.drop_table("story_duel_commands")
    op.drop_table("season_squad_members")
    op.drop_table("season_emotes")
    op.drop_table("refresh_tokens")
    op.drop_table("party_members")
    op.drop_table("party_invites")
    op.drop_table("wallets")
    op.drop_table("story_duels")
    op.drop_table("season_weekly")
    op.drop_table("season_story_progress")
    op.drop_table("season_squads")
    op.drop_table("season_players")
    op.drop_table("season_days")
    op.drop_table("season_characters")
    op.drop_table("season_chapter_clears")
    op.drop_table("player_stats")
    op.drop_table("player_skills")
    op.drop_table("player_sessions")
    op.drop_table("player_rivals")
    op.drop_table("player_reports")
    op.drop_table("player_mutes")
    op.drop_table("player_blocks")
    op.drop_table("player_achievements")
    op.drop_table("parties")
    op.drop_table("match_players")
    op.drop_table("match_analyses")
    op.drop_table("friendships")
    op.drop_table("fair_play_cases")
    op.drop_table("cosmetics_owned")
    op.drop_table("coin_ledger")
    op.drop_table("admin_sessions")
    op.drop_table("admin_audit")
    op.drop_table("seasons")
    op.drop_table("season_cues")
    op.drop_table("runtime_flags")
    op.drop_table("rule_embeddings")
    op.drop_table("players")
    op.drop_table("matches")
    op.drop_table("admin_users")
