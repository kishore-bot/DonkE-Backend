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

    postgres_dsn: PostgresDsn | None = None
    redis_dsn: RedisDsn | None = None
    auth_secret: SecretStr | None = None
    google_client_id: str | None = None
    redis_prefix: str = Field(default="donke", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    access_seconds: int = Field(default=1800, ge=60, le=3600)
    refresh_seconds: int = Field(default=604800, ge=3600, le=2592000)
    admin_session_seconds: int = Field(default=900, ge=60, le=3600)
    room_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    queue_ttl_seconds: int = Field(default=120, ge=30, le=600)
    bot_fill_seconds: float = Field(default=10, ge=0, le=30)
    claim_lease_seconds: float = Field(default=5, gt=0, le=30)
    matchmaking_poll_seconds: float = Field(default=0.25, gt=0, le=2)

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
        if self.queue_ttl_seconds <= self.bot_fill_seconds + self.claim_lease_seconds:
            raise ValueError("The queue TTL must exceed bot fill wait plus claim lease")
        return self
