"""Settings for pmis-project-service.

SECRET_KEY is the critical shared value across pmis-project-service,
pmis-user-service, and the monolith — it MUST match so JWTs minted by
user-service can be verified by this service.

extra='ignore' is important: the shared .env file may contain keys that
belong to docker-compose, the monolith, or user-service but not this
service.
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
    APP_NAME: str = "PMIS Project Service"
    APP_VERSION: str = "1.0.0"
    SERVICE_NAME: str = "pmis-project-service"
    DEBUG: bool = False

    # ---- Security (MUST match user-service + monolith) ----
    SECRET_KEY: str = Field(
        default="change-me-to-a-long-random-string-min-32-chars-shared-with-all-services",
        description=(
            "HS256 signing key — MUST be identical to user-service's and "
            "monolith's SECRET_KEY. JWTs are minted by user-service and "
            "verified locally here using this key."
        ),
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Grace window for the just-rotated-out refresh-token jti during
    # /users/refresh — prevents 401s on multi-tab races. Mirrors monolith.
    REFRESH_TOKEN_GRACE_SECONDS: int = 120

    # Doc 24 part 2: optional cap on subtask nesting depth. ``None`` (the
    # default) means unlimited.
    SUBTASK_MAX_NESTING_DEPTH: Optional[int] = None

    # ---- Database (same DB as monolith + user-service) ----
    DATABASE_URL: str = Field(
        default="postgresql://pmis:admin123@localhost:5432/pmis",
        description="Shared Postgres — same instance the other services connect to.",
    )
    DATABASE_URL_MIGRATIONS: Optional[str] = Field(
        default=None,
        description=(
            "Optional elevated-privilege URL used ONLY for "
            "``alembic upgrade head`` at startup. Falls back to "
            "DATABASE_URL when unset."
        ),
    )

    MIGRATIONS_AUTORUN: bool = True
    MIGRATIONS_REQUIRED: bool = True

    # ---- CORS / pagination ----
    CORS_ORIGINS: list[str] = ["*"]
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # ---- File attachments (NFS-backed in prod) ----
    ATTACHMENTS_STORAGE_BASE_PATH: str = Field(
        default="./local_uploads",
        description=(
            "Local filesystem path where attachment bytes are stored. In "
            "production this MUST be the NFS mount point (same as the "
            "monolith). In dev it's a local folder."
        ),
    )
    ATTACHMENTS_NFS_SERVER: str = Field(
        default="",
        description="Informational only. Surfaced via /health for ops visibility.",
    )
    ATTACHMENTS_NFS_EXPORT: str = Field(
        default="",
        description="Informational only. Surfaced via /health for ops visibility.",
    )
    ATTACHMENTS_MAX_BYTES: int = 26214400  # 25 MiB
    # Client-approved (post-demo) whitelist:
    #   Documents: pdf, docx, xlsx, txt, csv
    #   Images:    jpg, jpeg, png, heic
    #   Videos:    mp4, webm, mov
    ATTACHMENTS_ALLOWED_EXTENSIONS: str = (
        "pdf,docx,xlsx,txt,csv,jpg,jpeg,png,heic,mp4,webm,mov"
    )
    ATTACHMENTS_SUBDIR_STRATEGY: str = "year_month"
    ATTACHMENTS_RETENTION_DAYS: int = 90
    ATTACHMENTS_ON_UNAVAILABLE: str = "fail"

    # ---- Doc 35: external file server URLs ----
    FILE_SERVER_PUBLIC_BASE_URL: str = Field(
        default="",
        description=(
            "Public URL prefix for stored attachment files. When unset, "
            "URLs are stored as relative paths and the BE's local "
            "fallback route serves them."
        ),
    )
    FILE_SERVER_LOCAL_FALLBACK_ENABLED: bool = Field(
        default=True,
        description=(
            "Mount GET /files/{key} as a local fallback that streams "
            "bytes from ATTACHMENTS_STORAGE_BASE_PATH."
        ),
    )
    FILE_SERVER_BASE_URL: str = Field(
        default="",
        description=(
            "Internal URL of the file-server upload endpoint. When set, "
            "the BE forwards uploaded bytes there."
        ),
    )
    FILE_SERVER_AUTH_TOKEN: str = Field(
        default="",
        description="Auth token for FILE_SERVER_BASE_URL upload calls.",
    )

    # ---- Frontend base URL (used by some link templates) ----
    FRONTEND_BASE_URL: str = Field(
        default="",
        description="Public origin of the FE app, e.g. http://host:3000.",
    )

    # ---- Doc 36 division contact backfill defaults ----
    DIVISION_DEFAULT_EMAIL: str = Field(
        default="ops@pmis.example",
        description="Backfill / seed default for divisions.email.",
    )
    DIVISION_DEFAULT_PHONE: str = Field(
        default="+910000000000",
        description="Backfill / seed default for divisions.phone_number.",
    )

    # NOTE: OTP / 2FA / notification / bootstrap-admin settings live on
    # user-service. Not duplicated here.


settings = Settings()
