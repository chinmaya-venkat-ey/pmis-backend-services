"""Settings for pmis-user-service.

Mirrors the monolith's config pattern. SECRET_KEY is the critical shared
value between the two services — it MUST match the monolith's SECRET_KEY
so tokens minted here can be verified by the monolith.

extra='ignore' is important: the shared .env file may contain keys that
belong to docker-compose or the monolith but not this service.

Doc 37 part 2: env vars expanded to match monolith's auth/notification
surface (REQUIRE_2FA, OTP_*, NOTIFICATION_*, FRONTEND_BASE_URL,
OTP_HASH_PEPPER, UNIVERSAL_OTP_*, MIGRATIONS_*).
"""
from typing import Optional

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
    REFRESH_TOKEN_GRACE_SECONDS: int = 120

    # ---- Database (same DB as monolith) ----
    DATABASE_URL: str = Field(
        default="postgresql://pmis:admin123@localhost:5432/pmis",
        description="Shared Postgres — same instance the monolith connects to.",
    )
    # Optional separate URL for `alembic upgrade head` (admin role).
    DATABASE_URL_MIGRATIONS: Optional[str] = Field(
        default=None,
        description=(
            "Optional elevated-privilege URL used ONLY for "
            "`alembic upgrade head` at startup. Falls back to "
            "DATABASE_URL when unset."
        ),
    )

    # ---- Migration controls (doc 33 hotfix) ----
    # In the doc-37-part-2 architecture, the monolith owns migrations
    # for the shared DB. user-service should default MIGRATIONS_AUTORUN
    # to false in deploys where the monolith runs alembic — set true
    # only for local dev where user-service is the only writer.
    MIGRATIONS_AUTORUN: bool = Field(
        default=True,
        description=(
            "Whether init_db runs `alembic upgrade head` on boot. "
            "Set false in shared-DB deploys where the monolith owns "
            "migrations."
        ),
    )
    MIGRATIONS_REQUIRED: bool = Field(
        default=True,
        description=(
            "When True, alembic failure crashes boot. When False, "
            "logs the failure and continues — useful for the "
            "MIGRATIONS_AUTORUN=false case where alembic might not "
            "be runnable from this service's perspective."
        ),
    )

    # ---- CORS ----
    CORS_ORIGINS: list = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins for the FE.",
    )

    # ---- Bootstrap admin ----
    BOOTSTRAP_ADMIN_LOGIN: str = "admin"
    BOOTSTRAP_ADMIN_EMAIL: str = "admin@example.com"
    BOOTSTRAP_ADMIN_PASSWORD: str = "admin123"

    # ---- Pagination defaults ----
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # ---- 2FA + forgot-password (doc 33 change 3) ----
    REQUIRE_2FA: bool = Field(
        default=True,
        description=(
            "Global 2FA toggle. Per-user override via "
            "users.two_factor_enabled. Doc 35 parity: bootstrap admin "
            "is forced two_factor_enabled=True on every boot — the "
            "universal-OTP break-glass covers misconfigured dispatch."
        ),
    )
    OTP_TTL_SECONDS: int = 300
    OTP_RESEND_COOLDOWN_SECONDS: int = 60
    OTP_MAX_ATTEMPTS: int = 5
    OTP_CODE_LENGTH: int = 6
    OTP_HASH_PEPPER: str = Field(
        default="",
        description=(
            "Server-side pepper for HMAC-SHA256 hashing of OTP/reset "
            "tokens. Falls back to SECRET_KEY when empty. Set "
            "deployment-unique in production."
        ),
    )
    PASSWORD_RESET_TTL_SECONDS: int = 3600

    # FE base URL — used in password-reset email links.
    FRONTEND_BASE_URL: str = Field(
        default="",
        description=(
            "Public FE base URL. When set, the password-reset email "
            "embeds a clickable link FRONTEND_BASE_URL/reset-password"
            "?token=<token>. When unset, falls back to bare-token "
            "rendering in the email."
        ),
    )

    # ---- Notification client (doc 33 change 3 + doc 36) ----
    NOTIFICATION_CLIENT: str = Field(
        default="mock",
        description="'mock' (DB log only) or 'http' (real microservice).",
    )
    NOTIFICATION_SERVICE_URL: str = Field(
        default="",
        description="Base URL of PMIS-notification-service (used when NOTIFICATION_CLIENT=http).",
    )

    # ---- Universal OTP (operational break-glass) ----
    #
    # When ``UNIVERSAL_OTP_ENABLED=True``, ``/login/verify-otp`` accepts
    # ``UNIVERSAL_OTP_CODE`` (default ``000000``) for any user as their
    # login OTP, regardless of which OTP was actually generated. The
    # active OTP session row (created by ``/login`` and
    # ``/login/send-otp``) is still required. Used as a break-glass for
    # environments where email/SMS dispatch is broken or for demo flows.
    #
    # Default False. Production deploys MUST keep it false.
    UNIVERSAL_OTP_ENABLED: bool = Field(
        default=False,
        description=(
            "Break-glass / demo-only universal OTP. Do NOT enable in "
            "production. The /health endpoint surfaces this flag for "
            "external visibility."
        ),
    )
    UNIVERSAL_OTP_CODE: str = Field(
        default="000000",
        description="The fixed code accepted when UNIVERSAL_OTP_ENABLED.",
    )


settings = Settings()
