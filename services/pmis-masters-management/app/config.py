"""pmis-masters-management — application configuration.

Reads environment variables via Pydantic v2 Settings. masters-svc owns
schema `masters`: divisions, vendors, resource_types, project_categories,
activity_types, activity_statuses, milestone_statuses,
project_status_transitions, priorities, notification_templates.
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
    service_name: str = Field(default="pmis-masters-management")
    cors_origins: str = Field(default="http://localhost:3000")

    # === DB ===
    database_url: str = Field(default="postgresql+psycopg2://pmis_app:changeme@localhost:5432/pmis")
    database_url_migrations: Optional[str] = Field(default=None)

    # === JWT (verify only) ===
    secret_key: str = Field(default="replace-me-with-a-256-bit-secret")
    algorithm: str = Field(default="HS256")

    # === Catalog defaults ===
    division_default_email: Optional[str] = Field(default=None)
    division_default_phone: Optional[str] = Field(default=None)

    # === Pagination ===
    default_page_size: int = Field(default=20)
    max_page_size: int = Field(default=100)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
