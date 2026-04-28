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
