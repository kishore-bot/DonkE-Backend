from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DONKE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    practice_session_ttl_seconds: int = Field(default=3600, gt=0)
    practice_max_sessions: int = Field(default=128, gt=0)
    practice_sessions_per_client: int = Field(default=3, ge=1, le=50)
    practice_creates_per_minute: int = Field(default=10, ge=1, le=600)
    # Proxies whose X-Forwarded-For is trusted (the app is bound to loopback
    # and reached through Caddy). Clients outside these cannot spoof their IP.
    trusted_proxies: list[str] = Field(
        default=[
            "127.0.0.0/8",
            "::1/128",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
        ]
    )

    postgres_dsn: PostgresDsn | None = None
    redis_dsn: RedisDsn | None = None
    auth_secret: SecretStr | None = None
    # Encrypts admin TOTP secrets at rest. Unset: derived from auth_secret.
    admin_totp_key: SecretStr | None = None
    google_client_id: str | None = None
    demo_mode: bool = False
    redis_prefix: str = Field(default="donke", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    access_seconds: int = Field(default=1800, ge=60, le=3600)
    refresh_seconds: int = Field(default=604800, ge=3600, le=2592000)
    admin_session_seconds: int = Field(default=900, ge=60, le=3600)
    room_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    queue_ttl_seconds: int = Field(default=120, ge=30, le=600)
    bot_fill_seconds: float = Field(default=10, ge=0, le=30)
    claim_lease_seconds: float = Field(default=5, gt=0, le=30)
    matchmaking_poll_seconds: float = Field(default=0.25, gt=0, le=2)

    room_start_seconds: float = Field(default=3, ge=0, le=30)
    turn_seconds: float = Field(default=40, gt=0, le=120)
    bot_turn_seconds: float = Field(default=0.5, gt=0, le=5)
    match_minutes: int = Field(default=45, ge=1, le=120)
    match_archive_seconds: int = Field(default=86400, ge=60, le=604800)

    gemini_api_key: SecretStr | None = None
    gemini_text_model: str = "gemini-3.8-flash"
    gemini_voice_model: str = "gemini-3.8-flash-tts"
    gemini_embedding_model: str = "gemini-embedding-2"
    admin_ui_dir: str = "admin-ui"
    # Public HTTPS origin for share links, e.g. https://play.example.com.
    # Empty: links use the address the request arrived on (fine for local
    # development; set it in production behind a proxy).
    public_base_url: str = Field(
        default="", max_length=200, pattern=r"^(https://[A-Za-z0-9.-]+(:\d+)?)?$"
    )
    practice_hint_iterations: int = Field(default=200, ge=10, le=2000)
    ai_text_daily_calls: int = Field(default=250, ge=0, le=5000)
    ai_voice_daily_calls: int = Field(default=100, ge=0, le=5000)
    voice_concurrency: int = Field(default=2, ge=1, le=8)

    @model_validator(mode="after")
    def online_settings(self) -> Settings:
        online = (self.postgres_dsn, self.redis_dsn, self.auth_secret)
        if any(value is not None for value in online) and not all(
            value is not None for value in online
        ):
            raise ValueError(
                "Online mode requires PostgreSQL, Redis, and an auth secret"
            )
        if self.postgres_dsn and self.postgres_dsn.scheme != "postgresql+asyncpg":
            raise ValueError("PostgreSQL requires the postgresql+asyncpg scheme")
        if self.auth_secret and len(self.auth_secret.get_secret_value().encode()) < 32:
            raise ValueError("The auth secret must contain at least 32 bytes")
        if (
            self.admin_totp_key
            and len(self.admin_totp_key.get_secret_value().encode()) < 32
        ):
            raise ValueError("The admin TOTP key must contain at least 32 bytes")
        if self.queue_ttl_seconds <= self.bot_fill_seconds + self.claim_lease_seconds:
            raise ValueError("The queue TTL must exceed bot fill wait plus claim lease")
        return self
