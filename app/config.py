"""pmis-contract-management — application configuration.

Reads environment variables via Pydantic v2 Settings. All settings are
validated at startup.
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
    service_name: str = Field(default="pmis-contract-management")
    cors_origins: str = Field(default="http://localhost:3000")

    # === DB ===
    database_url: str = Field(default="postgresql+psycopg2://pmis_app:CHANGE-ME@localhost:5432/pmis")
    database_url_migrations: Optional[str] = Field(default=None)

    # === JWT (verify only) ===
    secret_key: str = Field(default="replace-me-with-a-256-bit-secret")
    algorithm: str = Field(default="HS256")

    # === Pagination ===
    default_page_size: int = Field(default=20)
    max_page_size: int = Field(default=100)

    # === Cross-service: project-management ===
    project_management_base_url: str = Field(
        default="http://10.1.131.199/projects",
        description="Base URL of pmis-project-management. Used by the evaluator to "
                    "resolve an activity's project_id at evaluation time.",
    )
    project_management_timeout_seconds: float = Field(default=5.0)

    # === Cross-service: user-management (the single Policy Decision Point) ===
    # Auth/RBAC is resolved by calling its /api/v3/authz/context endpoint —
    # this service no longer reads users.* itself. When unset, every authed
    # request is treated as anonymous (dev/standalone mode).
    user_management_service_url: Optional[str] = Field(default=None)
    user_management_service_timeout_seconds: float = Field(default=5.0)

    # === Cross-service: pmis-file-store (S3 microservice) ===
    # Base URL of pmis-file-store. When set, image-attachment routes
    # forward uploads/downloads/deletes to this service. When unset,
    # attachment endpoints return 503 "file-store not configured" so the
    # FE can show a friendly fallback.
    #
    # Default points at the VM's nginx exposure
    # (http://10.1.131.199/files) — flip via .env for local dev.
    file_store_service_url: Optional[str] = Field(
        default="http://10.1.131.199/files",
    )
    # Service-to-service bearer used when the inbound request has no
    # Authorization header (background jobs, anonymous flows). Per-request
    # bearer takes precedence — see FileStoreClient._headers.
    file_store_service_token: Optional[str] = Field(default=None)
    # Logical folder inside filestore. All SLA image uploads land here.
    file_store_default_folder: str = Field(default="sla-attachments")
    file_store_timeout_seconds: float = Field(default=30.0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
