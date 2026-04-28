import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from fastapi import HTTPException, status

from app.config import settings
from app.schemas.otp import OTPChannel
from app.services.email_service import get_email_service
from app.services.sms_service import get_sms_service
from app.utilities.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _OTPRecord:
    otp: str
    expires_at: float
    attempts: int = 0
    last_sent_at: float = field(default_factory=time.time)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class OTPService:
    """Generates, stores and verifies OTPs sent via SMS or email.

    NOTE: backed by an in-memory store; swap for Redis in production by
    replacing the `_store` interface.
    """

    def __init__(self) -> None:
        self._store: Dict[str, _OTPRecord] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(channel: OTPChannel, destination: str) -> str:
        return f"{channel.value}:{destination.lower()}"

    def _generate(self) -> str:
        length = max(4, min(10, settings.otp_length))
        upper = 10 ** length
        return str(secrets.randbelow(upper)).zfill(length)

    def send_otp(self, channel: OTPChannel, destination: str, purpose: str) -> dict:
        key = self._key(channel, destination)
        now = time.time()

        with self._lock:
            existing = self._store.get(key)
            if existing and (now - existing.last_sent_at) < settings.otp_resend_cooldown_seconds:
                wait = int(settings.otp_resend_cooldown_seconds - (now - existing.last_sent_at))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Please wait {wait}s before requesting a new OTP",
                )

            otp = self._generate()
            record = _OTPRecord(
                otp=otp,
                expires_at=now + settings.otp_ttl_seconds,
                last_sent_at=now,
            )
            self._store[key] = record

        text = (
            f"Your PIMS {purpose} OTP is {otp}. "
            f"It is valid for {settings.otp_ttl_seconds // 60} minutes."
        )

        if channel == OTPChannel.sms:
            get_sms_service().send(to=destination, message=text)
        else:
            get_email_service().send(
                to=[destination],
                subject=f"PIMS {purpose.title()} OTP",
                body=(
                    f"<p>Your PIMS <b>{purpose}</b> OTP is "
                    f"<b style='font-size:18px'>{otp}</b>.</p>"
                    f"<p>Valid for {settings.otp_ttl_seconds // 60} minutes.</p>"
                ),
                is_html=True,
            )

        return {
            "success": True,
            "message": f"OTP sent via {channel.value}",
            "channel": channel,
            "destination": destination,
            "expires_in_seconds": settings.otp_ttl_seconds,
            "request_id": record.request_id,
        }

    def verify_otp(self, channel: OTPChannel, destination: str, otp: str) -> dict:
        key = self._key(channel, destination)
        now = time.time()

        with self._lock:
            record: Optional[_OTPRecord] = self._store.get(key)
            if record is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No OTP requested for this destination",
                )

            if now > record.expires_at:
                self._store.pop(key, None)
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail="OTP has expired, please request a new one",
                )

            if record.attempts >= settings.otp_max_attempts:
                self._store.pop(key, None)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Maximum OTP attempts exceeded, please request a new one",
                )

            record.attempts += 1
            if not secrets.compare_digest(record.otp, otp):
                remaining = settings.otp_max_attempts - record.attempts
                return {
                    "success": False,
                    "message": f"Invalid OTP. {remaining} attempt(s) remaining.",
                    "verified": False,
                }

            self._store.pop(key, None)

        return {
            "success": True,
            "message": "OTP verified successfully",
            "verified": True,
        }


_otp_service: Optional[OTPService] = None


def get_otp_service() -> OTPService:
    global _otp_service
    if _otp_service is None:
        _otp_service = OTPService()
    return _otp_service
