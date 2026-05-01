"""Settings for pmis-project-service.

SECRET_KEY is the critical shared value across pmis-project-service,
pmis-user-service, and the monolith — it MUST match so JWTs minted by
user-service can be verified by this service.

extra='ignore' is important: the shared .env file may contain keys that
belong to docker-compose, the monolith, or user-service but not this
service.
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
    APP_NAME: str = "PMIS Project Service"
    APP_VERSION: str = "0.1.0"
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

    # ---- Database (same DB as monolith + user-service) ----
    DATABASE_URL: str = Field(
        default="postgresql://pmis:admin123@localhost:5432/pmis",
        description="Shared Postgres — same instance the other services connect to.",
    )

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
    # Legacy doc/xls/ppt/pptx + gif/webp were dropped at the client's
    # request. Re-enable here is a one-line config change; production
    # validation is enforced by both extension AND magic-byte content
    # sniffing in app/api/v3/attachments/services/upload.py.
    ATTACHMENTS_ALLOWED_EXTENSIONS: str = (
        "pdf,docx,xlsx,txt,csv,jpg,jpeg,png,heic,mp4,webm,mov"
    )
    ATTACHMENTS_SUBDIR_STRATEGY: str = "year_month"
    ATTACHMENTS_RETENTION_DAYS: int = 90
    ATTACHMENTS_ON_UNAVAILABLE: str = "fail"


settings = Settings()
