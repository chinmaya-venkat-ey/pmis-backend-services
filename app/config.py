"""pmis-project-management — application configuration.

Reads environment variables via Pydantic v2 Settings. All settings are
validated at startup. See ../../.env.example for the full matrix.
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
    service_name: str = Field(default="pmis-project-management")
    cors_origins: str = Field(default="http://localhost:3000")

    # === DB ===
    database_url: str = Field(default="postgresql+psycopg2://pmis_app:changeme@localhost:5432/pmis")
    database_url_migrations: Optional[str] = Field(default=None)

    # === JWT (verify only) ===
    secret_key: str = Field(default="replace-me-with-a-256-bit-secret")
    algorithm: str = Field(default="HS256")

    # === Attachments ===
    attachments_storage_base_path: str = Field(default="/var/lib/pmis/attachments")
    attachments_max_bytes: int = Field(default=26214400, description="25 MB per Q22")
    attachments_allowed_extensions: str = Field(
        default="pdf,docx,xlsx,txt,csv,jpg,jpeg,png,heic,mp4,webm,mov"
    )
    attachments_subdir_strategy: str = Field(default="year_month")
    attachments_retention_days: int = Field(default=90)
    attachments_on_unavailable: str = Field(default="fail")
    attachments_nfs_server: Optional[str] = Field(default=None)
    attachments_nfs_export: Optional[str] = Field(default=None)

    # === File server (external) ===
    file_server_public_base_url: Optional[str] = Field(default=None)
    file_server_local_fallback_enabled: bool = Field(default=True)
    file_server_base_url: Optional[str] = Field(default=None)
    file_server_auth_token: Optional[str] = Field(default=None)

    # === Frontend reference (HAL link builder) ===
    frontend_base_url: Optional[str] = Field(default=None)

    # === Pagination ===
    default_page_size: int = Field(default=20)
    max_page_size: int = Field(default=100)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
