"""pmis-user-management — application configuration.

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
    env: str = Field(default="development", description="development|staging|production")
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="text", description="text|json")
    root_path: str = Field(default="", description="Optional ROOT_PATH from nginx (per Decision 8a)")
    service_name: str = Field(default="pmis-user-management")
    cors_origins: str = Field(default="http://localhost:3000", description="comma-separated; used only when ENV=development")

    # === DB ===
    database_url: str = Field(default="postgresql+psycopg2://pmis_app:CHANGE-ME@localhost:5432/pmis")
    database_url_migrations: Optional[str] = Field(default=None)

    # === JWT ===
    secret_key: str = Field(default="replace-me-with-a-256-bit-secret")
    algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=120)
    refresh_token_expire_days: int = Field(default=7)
    refresh_token_grace_seconds: int = Field(default=120)

    # === Bootstrap (only consumed by alembic bootstrap data-migration) ===
    bootstrap_superadmin_login: str = Field(default="superadmin")
    bootstrap_superadmin_email: str = Field(default="superadmin@example.com")
    superadmin_bootstrap_password: Optional[str] = Field(default=None, description="Q33: unset after first migration")

    # === 2FA / OTP ===
    require_2fa: bool = Field(default=True)
    otp_ttl_seconds: int = Field(default=300)
    otp_resend_cooldown_seconds: int = Field(default=60)
    otp_max_attempts: int = Field(default=5)
    otp_code_length: int = Field(default=6)
    otp_hash_pepper: str = Field(default="replace-me")
    password_reset_ttl_seconds: int = Field(default=3600)

    # Break-glass — Q14: startup error if true in production
    universal_otp_enabled: bool = Field(default=False)
    universal_otp_code: str = Field(default="000000")

    # === Outbound to notification-svc ===
    notification_service_url: str = Field(default="http://pmis-notification-management:8002")
    notification_service_timeout_seconds: float = Field(default=10.0)
    notification_client: str = Field(default="mock", description="mock|http")

    # === Pagination ===
    default_page_size: int = Field(default=20)
    max_page_size: int = Field(default=100)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
