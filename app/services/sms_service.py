import uuid
from typing import Optional

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.utilities.logger import get_logger

logger = get_logger(__name__)


class SMSProviderError(Exception):
    pass


class _MockSMSProvider:
    name = "mock"

    def send(self, to: str, message: str) -> str:
        logger.info("[MOCK SMS] to=%s | msg=%s", to, message)
        return f"mock-{uuid.uuid4()}"


class _TwilioSMSProvider:
    name = "twilio"

    def send(self, to: str, message: str) -> str:
        if not (settings.twilio_account_sid and settings.twilio_auth_token):
            raise SMSProviderError("Twilio credentials are not configured")
        if not settings.sms_from_number:
            raise SMSProviderError("SMS_FROM_NUMBER is not configured")
        try:
            from twilio.rest import Client
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            msg = client.messages.create(
                body=message,
                from_=settings.sms_from_number,
                to=to,
            )
            return msg.sid
        except Exception as exc:
            raise SMSProviderError(f"Twilio error: {exc}") from exc


class _Msg91SMSProvider:
    name = "msg91"

    def send(self, to: str, message: str) -> str:
        if not settings.msg91_api_key:
            raise SMSProviderError("MSG91_API_KEY is not configured")
        # MSG91 expects mobile without leading +
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
                raise SMSProviderError(f"MSG91 error {resp.status_code}: {resp.text}")
            return resp.text.strip() or f"msg91-{uuid.uuid4()}"
        except httpx.HTTPError as exc:
            raise SMSProviderError(f"MSG91 HTTP error: {exc}") from exc


class SMSService:
    """Provider-agnostic SMS service. Provider chosen at runtime via env."""

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
        raise SMSProviderError(f"Unsupported SMS provider: {name}")

    def send(self, to: str, message: str) -> dict:
        try:
            message_id = self._provider.send(to, message)
            return {
                "success": True,
                "message": "SMS sent successfully",
                "provider": self._provider.name,
                "message_id": message_id,
            }
        except SMSProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            )


_sms_service: Optional[SMSService] = None


def get_sms_service() -> SMSService:
    global _sms_service
    if _sms_service is None:
        _sms_service = SMSService()
    return _sms_service
