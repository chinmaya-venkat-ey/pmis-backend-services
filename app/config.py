"""pmis-file-store — application configuration.

All values are read from environment variables (or .env file for local dev).
Zero defaults contain secrets or bucket names — those must be supplied
via environment. Non-sensitive defaults are provided for ergonomic local dev.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === Cross-service ===
    env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="text")
    root_path: str = Field(default="")
    service_name: str = Field(default="pmis-file-store")
    cors_origins: str = Field(default="http://localhost:3000")

    # === Database ===
    # Same shared PostgreSQL instance as all PMIS microservices.
    # This service creates/owns the `files` schema.
    database_url: str = Field(
        default="postgresql+psycopg2://pmis_user:changeme@localhost:5432/pmis_db"
    )
    database_url_migrations: Optional[str] = Field(default=None)

    # === JWT (verify only — user-svc is the issuer) ===
    secret_key: str = Field(default="replace-me-with-same-key-as-user-svc")
    algorithm: str = Field(default="HS256")

    # === AWS S3 ===
    # Required — no default. Must be supplied via env.
    s3_bucket_name: str = Field(..., description="S3 bucket name.")
    s3_region: str = Field(default="ap-south-1", description="AWS region.")
    aws_access_key_id: str = Field(..., description="AWS access key ID.")
    aws_secret_access_key: str = Field(..., description="AWS secret access key.")

    # Override for MinIO / LocalStack. Leave blank for real AWS.
    s3_endpoint_url: Optional[str] = Field(
        default=None,
        description="Custom S3 endpoint URL (MinIO, LocalStack). Leave blank for real AWS.",
    )

    # Root prefix inside the bucket. All objects will be under this path.
    # E.g. "pmis/prod" → key = "pmis/prod/project-attachments/..."
    s3_key_prefix: str = Field(default="pmis")

    # How long (seconds) pre-signed GET URLs remain valid.
    s3_presigned_url_expires: int = Field(default=3600)

    # When set, download URLs are permanent CDN/public URLs instead of
    # time-limited pre-signed URLs.
    # E.g. "https://files.pmis.example.com"
    s3_public_url_base: Optional[str] = Field(default=None)

    # === Upload constraints ===
    # Maximum allowed file size (bytes). Default: 25 MB.
    max_upload_bytes: int = Field(default=26214400)

    # Comma-separated list of allowed file extensions (without leading dot).
    allowed_extensions: str = Field(
        default="pdf,docx,xlsx,txt,csv,jpg,jpeg,png,heic,mp4,webm,mov"
    )

    # === Pagination ===
    default_page_size: int = Field(default=20)
    max_page_size: int = Field(default=100)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
