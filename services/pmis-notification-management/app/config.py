"""pmis-notification-management — application configuration.

Reads environment variables via Pydantic v2 Settings.

Post-refactor, notification-svc owns NO tables (Q3 moved notification_templates
to masters; Q13 moved OTP storage to users.otp_codes). It reads
masters.notification_templates and users.* cross-schema for dispatch + cron.
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
    service_name: str = Field(default="pmis-notification-management")
    cors_origins: str = Field(default="http://localhost:3000")

    # === DB (cross-schema reads only) ===
    database_url: str = Field(default="postgresql+psycopg2://pmis_app:changeme@localhost:5432/pmis")
    database_url_migrations: Optional[str] = Field(default=None)

    # === JWT (verify only) ===
    secret_key: str = Field(default="replace-me-with-a-256-bit-secret")
    algorithm: str = Field(default="HS256")

    # === Email ===
    email_provider: str = Field(default="smtp", description="smtp|sendgrid")
    email_from_address: str = Field(default="no-reply@pims.example.com")
    email_from_name: str = Field(default="PMIS Notification")
    smtp_host: str = Field(default="localhost")
    smtp_port: int = Field(default=587)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_use_tls: bool = Field(default=True)
    sendgrid_api_key: str = Field(default="")

    # === SMS ===
    sms_provider: str = Field(default="mock", description="mock|twilio|msg91")
    sms_from_number: str = Field(default="")
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    msg91_api_key: str = Field(default="")
    msg91_sender_id: str = Field(default="PMISAP")
    msg91_route: str = Field(default="4")

    # === Cron ===
    cron_shared_secret: str = Field(default="", description="X-Cron-Secret header for /cron endpoints")
    deadline_window_days: int = Field(default=5)

    # === Frontend reference (HAL link builder) ===
    frontend_base_url: Optional[str] = Field(default=None)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
