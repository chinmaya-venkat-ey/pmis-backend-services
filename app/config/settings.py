from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "PIMS-NOTIFICATION"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True
    api_prefix: str = "/api/v1"

    # Logging
    log_level: str = "INFO"

    # CORS
    cors_origins: str = "*"

    # Email provider
    email_provider: str = "smtp"
    email_from_address: str = "no-reply@pims.example.com"
    email_from_name: str = "PIMS Notification"

    # SMTP
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    # SendGrid
    sendgrid_api_key: str = ""

    # SMS provider
    sms_provider: str = "mock"
    sms_from_number: str = ""

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""

    # MSG91
    msg91_api_key: str = ""
    msg91_sender_id: str = "PIMSAP"
    msg91_route: str = "4"

    # OTP
    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 30

    # ---- Doc 38: database + auth + template rendering -----------------
    # Shared Postgres with monolith + user-service. SQLite fallback for
    # local-dev / tests. ``MIGRATIONS_AUTORUN=false`` is the default in
    # shared-DB deploys (monolith owns alembic).
    database_url: str = Field(
        default="sqlite:///./notification_service.db",
        description="Postgres URL (shared with monolith) or SQLite path for dev.",
    )
    migrations_autorun: bool = False
    migrations_required: bool = True

    # Shared SECRET_KEY — MUST match monolith + user-service so JWTs
    # minted by user-service verify here.
    secret_key: str = Field(
        default="change-me-to-a-long-random-string-min-32-chars-shared-with-backend",
        description="HS256 signing key — identical to monolith and user-service.",
    )
    algorithm: str = "HS256"

    # Used by template_service when rendering password-reset emails AND
    # by the daily-digest cron when rendering the portal link.
    frontend_base_url: str = ""

    # ---- Daily deadline-digest cron ----------------------------------
    # ``cron_shared_secret`` gates POST /api/v1/notifications/cron/daily-digest.
    # The DevOps cron caller must send ``X-Cron-Secret: <value>`` on every
    # request. Empty string means the endpoint is disabled (returns 503)
    # to keep boot-time safe defaults — must be set explicitly in deploy.
    cron_shared_secret: str = ""
    # ``deadline_window_days`` — how many days of look-ahead the cron
    # scans. 5 = include items ending today through today+5 (inclusive).
    # Overdue items (end_date < today) are always included regardless.
    deadline_window_days: int = 5

    @field_validator("email_provider", "sms_provider")
    @classmethod
    def lower_provider(cls, v: str) -> str:
        return v.lower().strip()

    def cors_origin_list(self) -> List[str]:
        if not self.cors_origins or self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
