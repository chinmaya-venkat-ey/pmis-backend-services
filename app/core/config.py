"""Settings for pmis-user-service.

Mirrors the monolith's config pattern. SECRET_KEY is the critical shared
value between the two services — it MUST match the monolith's SECRET_KEY
so tokens minted here can be verified by the monolith.

extra='ignore' is important: the shared .env file may contain keys that
belong to docker-compose or the monolith but not this service.
"""
from pydantic_settings import BaseSettings
from pydantic import ConfigDict, Field


class Settings(BaseSettings):
    """Application settings, env-driven via .env."""
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- App ----
    APP_NAME: str = "PMIS User Service"
    APP_VERSION: str = "0.1.0"
    SERVICE_NAME: str = "pmis-user-service"
    DEBUG: bool = False

    # ---- Security (MUST match the monolith's values) ----
    SECRET_KEY: str = Field(
        default="change-me-to-a-long-random-string-min-32-chars-shared-with-backend",
        description="HS256 signing key — MUST be identical to the monolith's SECRET_KEY.",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ---- Database (same DB as monolith in phase 1) ----
    DATABASE_URL: str = Field(
        default="postgresql://pmis:admin123@localhost:5432/pmis",
        description="Shared Postgres — same instance the monolith connects to.",
    )

    # ---- Bootstrap admin ----
    BOOTSTRAP_ADMIN_LOGIN: str = "admin"
    BOOTSTRAP_ADMIN_EMAIL: str = "admin@example.com"
    BOOTSTRAP_ADMIN_PASSWORD: str = "admin123"


settings = Settings()
