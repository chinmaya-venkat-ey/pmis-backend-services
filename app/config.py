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
    database_url: str = Field(default="postgresql+psycopg2://pmis_app:CHANGE-ME@localhost:5432/pmis")
    database_url_migrations: Optional[str] = Field(default=None)

    # === JWT (verify only) ===
    secret_key: str = Field(default="replace-me-with-a-256-bit-secret")
    algorithm: str = Field(default="HS256")

    # === Attachments ===
    attachments_storage_base_path: str = Field(default="/var/lib/pmis/attachments")
    attachments_max_bytes: int = Field(default=26214400, description="25 MB per Q22")
    # Single allow-list for EVERY attachment surface (project / milestone /
    # activity / task / subtask / comments / meeting). Legacy Office formats
    # (.doc/.xls/.ppt) sit alongside the OOXML ones (.docx/.xlsx/.pptx);
    # magic-byte verification recognises all of them (see
    # utilities/file_signature.py).
    attachments_allowed_extensions: str = Field(
        default="pdf,doc,docx,xls,xlsx,ppt,pptx,txt,csv,jpg,jpeg,png,heic,mp4,webm,mov"
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

    # === pmis-file-store (S3 microservice) ===
    # When set, project-svc delegates all uploads/deletes to file-svc over HTTP
    # instead of writing to the NFS mount. Set to the internal service URL,
    # e.g. "http://pmis-file-store:8005".
    file_store_service_url: Optional[str] = Field(default=None)
    # Service-to-service JWT used by file_store requests.
    # Must be a valid token accepted by file-svc's auth middleware
    # (same SECRET_KEY). Generate via user-svc or share a long-lived admin token.
    file_store_service_token: Optional[str] = Field(default=None)
    # Default logical folder sent to file-svc when no entity-specific folder
    # is provided. Callers can override per-upload.
    file_store_default_folder: str = Field(default="project-attachments")

    # === Activity Workflow (external Java microservice) ===
    # Base URL of the DIGIT-style workflow service that owns the activity
    # approval state machine. PMIS proxies SUBMIT/APPROVE/REJECT/UPDATE
    # to it and reads transition history for the Approval Inbox.
    # Leave unset to operate in mock mode (synthetic responses).
    workflow_service_url: Optional[str] = Field(default=None)
    workflow_service_timeout_seconds: float = Field(default=10.0)
    # Override mode: ``real`` | ``mock``. When unset, defaults to ``real``
    # if ``workflow_service_url`` is configured, ``mock`` otherwise.
    workflow_client: Optional[str] = Field(default=None)

    # === Notification dispatch (PMIS-notification-service) ===
    # Used by the approval-inbox transition proxy to email reviewers /
    # the activity vendor when state changes. Leave the URL blank to
    # operate in mock mode (dispatch is logged, not sent).
    notification_service_url: Optional[str] = Field(default=None)
    notification_service_timeout_seconds: float = Field(default=5.0)
    notification_client: Optional[str] = Field(default=None)

    # === User management (PMIS-user-management) ===
    # Used by team-page save to bulk-replace project-scoped role
    # assignments (orgUser section). The caller's Authorization header
    # is forwarded so user-mgmt enforces ``project_members:update``
    # against the actual caller (no service-account elevation).
    # Leave the URL blank to operate in mock mode (orgUser diff is
    # logged and skipped; local writes still proceed).
    user_management_service_url: Optional[str] = Field(default=None)
    user_management_service_timeout_seconds: float = Field(default=5.0)
    user_management_client: Optional[str] = Field(default=None)

    # === Contract management (PMIS-contract-management) ===
    # Used by PaymentPageService to fetch SLA quarterly-settlement rows
    # (Phase D) so the payment page renders LD deductions per quarter
    # alongside cost items. The caller's Authorization header is forwarded
    # — contract-mgmt gates the settlement endpoints on the same JWT via
    # its own auth middleware. Leave blank → payment page renders without
    # the LD block (soft-fail).
    contract_management_base_url: Optional[str] = Field(default=None)
    contract_management_timeout_seconds: float = Field(default=5.0)

    # === Leave management (PMIS-leave-management, Java) — designation rates ===
    # Live source for per-designation, per-contract-year monthly rate cards used
    # to cost a resource-based activity's planned resources. The caller's
    # Authorization header is forwarded. Blank => rates resolve to 0 (soft-fail);
    # the payment page still renders. Base includes the host, e.g.
    # "http://10.1.131.199:8019". Set to "mock" to use the built-in stub (local).
    leave_management_base_url: Optional[str] = Field(default=None)
    leave_management_timeout_seconds: float = Field(default=5.0)

    # === Ticket service (PMIS-Ticket-service, Java) ===
    # Read-only source for the dashboard's tickets block. Leave the URL
    # blank to degrade tickets to available:false. Base must include the
    # service context path, e.g. "http://pmis-ticket-service:8081/ticket-service".
    # The caller's bearer token is forwarded (the Java service validates it
    # via user-svc introspect).
    ticket_service_url: Optional[str] = Field(default=None)
    ticket_service_timeout_seconds: float = Field(default=6.0)
    # Max tickets pulled in one list call for client-side aggregation.
    ticket_service_list_cap: int = Field(default=2000)

    # === Meeting/MoM governance service (PMIS-meeting-mom-governance, Java) ===
    # Read-only source for the dashboard's meetings block. Blank => degrade
    # to available:false. Base must include the context path, e.g.
    # "http://pmis-meeting-mom:8080/meetings".
    meeting_service_url: Optional[str] = Field(default=None)
    meeting_service_timeout_seconds: float = Field(default=6.0)
    meeting_service_list_cap: int = Field(default=2000)

    # === Contract management (PMIS-contract-management) ===
    # Source for the dashboard's SLA compliance blocks. Blank => SLA degrades
    # to available:false. Base must include the service's /api/v3 host, e.g.
    # "http://pmis-contract-management:8005".
    contract_management_base_url: Optional[str] = Field(default=None)
    contract_management_timeout_seconds: float = Field(default=6.0)

    # === Leave management (PMIS-leave-management, Java) — designation rates ===
    # Live per-designation per-contract-year rate cards for resource costing.
    # Blank => rates 0 (soft-fail). "mock" => built-in stub for local harness.
    leave_management_base_url: Optional[str] = Field(default=None)
    leave_management_timeout_seconds: float = Field(default=5.0)

    # === Dashboard snapshot cron ===
    # Shared secret the scheduler must send as the ``X-Cron-Secret`` header
    # to POST /api/v3/dashboard/cron/snapshot (which persists the day's KPI
    # values for delta/spark derivation). Blank => the endpoint is disabled
    # (returns 403) so it can never be triggered anonymously in prod.
    cron_shared_secret: str = Field(default="")

    # === Frontend reference (HAL link builder) ===
    frontend_base_url: Optional[str] = Field(default=None)

    # === Pagination ===
    default_page_size: int = Field(default=20)
    max_page_size: int = Field(default=100)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
