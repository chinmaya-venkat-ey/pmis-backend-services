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

    # === Cross-service: pmis-file-store (S3 microservice, preferred) ===
    # Mirrors the env-var names used by pmis-project-management so a single
    # .env line can flip storage for both services. Resolution order in
    # ``dependencies.get_file_store_client``:
    #   1. file_store_service_url  → HttpFileStoreClient   (S3 microservice)
    #   2. file_server_local_fallback_enabled → LocalFileClient (NFS / disk)
    #   3. neither set            → attachment routes return 503
    #
    # Default for file_store_service_url points at the VM's nginx exposure
    # (http://10.1.131.199/files) so prod Just Works; override in .env for
    # local dev to force the NFS fallback.
    file_store_service_url: Optional[str] = Field(
        default="http://10.1.131.199/files",
    )
    file_store_service_token: Optional[str] = Field(default=None)
    file_store_default_folder: str = Field(default="sla-attachments")
    file_store_timeout_seconds: float = Field(default=30.0)

    # === NFS / local-disk fallback (matches project-mgmt naming) ===
    # Used when file_store_service_url is unset. Files are written under
    # file_server_local_dir and exposed as
    # ``{file_server_public_base_url}/{storage_key}``. If the base is empty
    # the URL is just the relative storage key — fine for dev where you
    # only care about the file_id round-trip.
    file_server_local_fallback_enabled: bool = Field(default=True)
    file_server_local_dir: str = Field(
        default="./uploads/sla-attachments",
        description="Local directory the NFS-fallback client writes bytes to.",
    )
    file_server_public_base_url: Optional[str] = Field(
        default=None,
        description="Public URL prefix served by nginx/CDN over the local dir. "
                    "Empty in dev — the URL stored on the row is then a "
                    "relative path.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
