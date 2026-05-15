"""SMS service — provider-agnostic dispatch.

Provider chosen at runtime via SMS_PROVIDER env var (`mock` | `twilio` | `msg91`).

Ported from
  C:\\Programming\\PMIS\\PMIS-notification-service\\app\\services\\sms_service.py:1-112
with these adjustments:
  - Raises `core.errors.ProviderError` instead of `HTTPException(502)` (PLAN.md §2.6).
"""
from __future__ import annotations

import uuid
from typing import Optional

import httpx

from app.config import settings
from app.core.errors import ProviderError
from app.utilities.logger import get_logger

logger = get_logger(__name__)


class _MockSMSProvider:
    name = "mock"

    def send(self, to: str, message: str) -> str:
        logger.info("[MOCK SMS] to=%s | msg=%s", to, message)
        return f"mock-{uuid.uuid4()}"


class _TwilioSMSProvider:
    name = "twilio"

    def send(self, to: str, message: str) -> str:
        if not (settings.twilio_account_sid and settings.twilio_auth_token):
            raise ProviderError(
                "Twilio credentials not configured",
                code="SMS_TWILIO_NOT_CONFIGURED",
            )
        if not settings.sms_from_number:
            raise ProviderError(
                "SMS_FROM_NUMBER not configured",
                code="SMS_FROM_NUMBER_MISSING",
            )
        try:
            from twilio.rest import Client  # type: ignore
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            msg = client.messages.create(
                body=message,
                from_=settings.sms_from_number,
                to=to,
            )
            return msg.sid
        except Exception as exc:
            raise ProviderError(
                f"Twilio error: {exc}",
                code="SMS_TWILIO_ERROR",
                details={"provider": "twilio"},
            ) from exc


class _Msg91SMSProvider:
    name = "msg91"

    def send(self, to: str, message: str) -> str:
        if not settings.msg91_api_key:
            raise ProviderError(
                "MSG91_API_KEY not configured",
                code="SMS_MSG91_NOT_CONFIGURED",
            )
        # MSG91 expects mobile WITHOUT leading +
        mobile = to.lstrip("+")
        params = {
            "authkey": settings.msg91_api_key,
            "mobiles": mobile,
            "message": message,
            "sender": settings.msg91_sender_id,
            "route": settings.msg91_route,
            "country": "0",
        }
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get("https://api.msg91.com/api/sendhttp.php", params=params)
            if resp.status_code != 200:
                raise ProviderError(
                    f"MSG91 error {resp.status_code}: {resp.text}",
                    code="SMS_MSG91_ERROR",
                    details={"provider": "msg91", "status_code": resp.status_code},
                )
            return resp.text.strip() or f"msg91-{uuid.uuid4()}"
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"MSG91 HTTP error: {exc}",
                code="SMS_MSG91_HTTP_ERROR",
            ) from exc


class SMSService:
    """Provider-agnostic SMS service. Chosen at runtime via settings.sms_provider."""

    def __init__(self) -> None:
        self.provider_name = settings.sms_provider
        self._provider = self._build_provider(self.provider_name)

    def _build_provider(self, name: str):
        if name == "mock":
            return _MockSMSProvider()
        if name == "twilio":
            return _TwilioSMSProvider()
        if name == "msg91":
            return _Msg91SMSProvider()
        raise ProviderError(
            f"Unsupported SMS provider: {name}",
            code="SMS_PROVIDER_UNSUPPORTED",
        )

    def send(self, to: str, message: str) -> dict:
        """Send via configured provider. Returns provider's response info.

        Raises ProviderError on failure (translated to HTTP 502).
        """
        message_id = self._provider.send(to, message)
        return {
            "success": True,
            "message": "SMS sent successfully",
            "provider": self._provider.name,
            "message_id": message_id,
        }


_sms_service: Optional[SMSService] = None


def get_sms_service() -> SMSService:
    """Lazy singleton accessor."""
    global _sms_service
    if _sms_service is None:
        _sms_service = SMSService()
    return _sms_service
