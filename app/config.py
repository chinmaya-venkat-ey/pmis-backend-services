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

    # Shared secret the scheduler sends as ``X-Cron-Secret`` to trigger the
    # daily SLA evaluation (POST /api/v3/sla-compliance/cron/run). Blank
    # disables the endpoint (403) so it can't be triggered anonymously.
    cron_shared_secret: str = Field(default="")
    algorithm: str = Field(default="HS256")

    # === Pagination ===
    default_page_size: int = Field(default=20)
    max_page_size: int = Field(default=100)

    # === Cross-service: project-management ===
    # Base URL set via env (Docker: PROJECT_MANAGEMENT_BASE_URL). Blank
    # → the evaluator falls back to the DB cross-schema resolver.
    project_management_base_url: Optional[str] = Field(
        default=None,
        description="Base URL of pmis-project-management. Used by the evaluator to "
                    "resolve an activity's project_id at evaluation time.",
    )
    project_management_timeout_seconds: float = Field(default=5.0)

    # === Cross-service: notification service (email + SMS dispatch) ===
    # Used by the "activity completed → auto-evaluate SLAs" workflow to
    # email project + activity owners when an SLA on the completed
    # activity needs manual input (formula_type not in _DATE_DERIVABLE).
    # Mirrors the project-mgmt notification client pattern. ``mock`` mode
    # logs the call without sending — safe default for local dev.
    # Base URL of pmis-notification-service. Left blank by default so
    # local dev doesn't accidentally hit a shared VM; deployment
    # env-vars set the real value (Docker: NOTIFICATION_SERVICE_URL).
    # When blank the client falls back to ``mock`` mode automatically.
    notification_service_url: Optional[str] = Field(default=None)
    notification_service_timeout_seconds: float = Field(default=5.0)
    notification_client: str = Field(
        default="real",
        description="'real' to POST to notification-svc, 'mock' to log only.",
    )

    # === Cross-service: user-management (the single Policy Decision Point) ===
    # Auth/RBAC is resolved by calling its /api/v3/authz/context endpoint —
    # this service no longer reads users.* itself. When unset, every authed
    # request is treated as anonymous (dev/standalone mode).
    user_management_service_url: Optional[str] = Field(default=None)
    user_management_service_timeout_seconds: float = Field(default=5.0)

    # === Cross-service: leave-management ===
    # Used by NpqpService (Phase C) to fetch F (planned quarterly staff cost).
    # NpqpService calls GET /api/attendance/cost/monthly per (year, month) and
    # sums the per-resource ``cost`` fields across the quarter's 3 months.
    # Leave-mgmt already folds paid-leave, half-day, and RFP §5.24.1
    # relaxation into that value, so NpqpService just sums.
    #
    # Auth — JWT-forwarding. The caller's Authorization header is
    # forwarded verbatim from every settlement/npqp GET into leave-mgmt.
    # No service-account credentials required. Since every trigger is
    # user-initiated (event-driven model, no cron), there's always a
    # bearer available. Missing bearer → NpqpService returns 'unavailable'.
    leave_management_base_url: Optional[str] = Field(default=None)
    leave_management_timeout_seconds: float = Field(default=10.0)
    # Retired env vars (previously required for service-account login flow;
    # kept as unused config keys temporarily so container deploys don't error
    # on unknown env vars — safe to remove from container env at any time):
    #   PMIS_SERVICE_ACCOUNT_LOGIN, PMIS_SERVICE_ACCOUNT_PASSWORD,
    #   PMIS_SERVICE_ACCOUNT_OTP. All three are no longer read by any code
    #   path. Pydantic settings ignores env vars not declared here, so
    #   they'll silently be dropped on next deploy.

    # === SLA image attachments — NFS-first, S3 microservice optional ===
    #
    # The contract module mirrors pmis-project-management's storage setup
    # so a single NFS mount holds attachments for the whole platform.
    # Resolution order in dependencies.get_file_store_client():
    #   1. file_store_service_url      → HttpFileStoreClient (S3 svc)
    #   2. file_server_local_fallback_enabled → LocalFileClient (NFS)
    #   3. neither                       → attachment routes return 503.
    #
    # Defaults below match what project-mgmt uses on the VM
    # (/mnt/pmis_files, nginx exposes /projects/files at the public URL).
    # The contract module writes to the same mount under a
    # ``sla-attachments/`` sub-folder so projects + SLAs share NFS
    # cleanly without filename collisions.
    file_store_service_url: Optional[str] = Field(
        default=None,
        description="Set ONLY when pmis-file-store (S3 microservice) is deployed. "
                    "Leave empty to use the NFS fallback that project-mgmt also uses.",
    )
    file_store_service_token: Optional[str] = Field(default=None)
    file_store_default_folder: str = Field(default="sla-attachments")
    file_store_timeout_seconds: float = Field(default=30.0)

    # === NFS / local-disk fallback (same mount as project-mgmt) ===
    file_server_local_fallback_enabled: bool = Field(default=True)
    file_server_local_dir: str = Field(
        default="/mnt/pmis_files",
        description="NFS mount point inside the container. Same path project-mgmt uses. "
                    "Set to a local dir (./uploads) for local dev.",
    )
    file_server_public_base_url: Optional[str] = Field(
        default=None,
        description="Public URL prefix served by nginx over the NFS mount "
                    "(env: FILE_SERVER_PUBLIC_BASE_URL). We reuse project-mgmt's "
                    "/projects/files location so the same nginx block serves both. "
                    "Empty in dev = relative URLs.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
