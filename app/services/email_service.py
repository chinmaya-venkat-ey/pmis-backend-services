"""Email service — provider-agnostic dispatch.

Provider chosen at runtime via EMAIL_PROVIDER env var (`smtp` | `sendgrid`).

Ported from
  C:\\Programming\\PMIS\\PMIS-notification-service\\app\\services\\email_service.py:1-170
with these adjustments:
  - Raises `core.errors.ProviderError` instead of `HTTPException(502)` (PLAN.md §2.6).
    The exception_handler in app/middleware/error_handler.py translates it to 502.
  - SMTPProvider / SendGridProvider class internals unchanged (vetted behaviour).
"""
from __future__ import annotations

import smtplib
import ssl
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

import httpx

from app.config import settings
from app.core.errors import ProviderError
from app.utilities.logger import get_logger

logger = get_logger(__name__)


class _SMTPProvider:
    name = "smtp"

    def send(
        self,
        to: List[str],
        subject: str,
        body: str,
        is_html: bool,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> str:
        msg = MIMEMultipart("alternative")
        msg["From"] = f'{settings.email_from_name} <{settings.email_from_address}>'
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc)

        mime_subtype = "html" if is_html else "plain"
        msg.attach(MIMEText(body, mime_subtype, "utf-8"))

        recipients = list(to) + list(cc or []) + list(bcc or [])
        message_id = f"smtp-{uuid.uuid4()}"

        try:
            if settings.smtp_use_tls:
                ssl_ctx = ssl.create_default_context()
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=ssl_ctx)
                    smtp.ehlo()
                    if settings.smtp_username:
                        smtp.login(settings.smtp_username, settings.smtp_password)
                    smtp.sendmail(settings.email_from_address, recipients, msg.as_string())
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                    if settings.smtp_username:
                        smtp.login(settings.smtp_username, settings.smtp_password)
                    smtp.sendmail(settings.email_from_address, recipients, msg.as_string())
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)
            raise ProviderError(
                f"SMTP send failed: {exc}",
                code="EMAIL_SMTP_ERROR",
                details={"provider": "smtp"},
            ) from exc

        logger.info("Email sent via SMTP to %s", recipients)
        return message_id


class _SendGridProvider:
    name = "sendgrid"

    def send(
        self,
        to: List[str],
        subject: str,
        body: str,
        is_html: bool,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> str:
        if not settings.sendgrid_api_key:
            raise ProviderError(
                "SENDGRID_API_KEY is not configured",
                code="EMAIL_SENDGRID_NOT_CONFIGURED",
            )

        personalization: dict = {"to": [{"email": e} for e in to]}
        if cc:
            personalization["cc"] = [{"email": e} for e in cc]
        if bcc:
            personalization["bcc"] = [{"email": e} for e in bcc]

        payload = {
            "personalizations": [personalization],
            "from": {
                "email": settings.email_from_address,
                "name": settings.email_from_name,
            },
            "subject": subject,
            "content": [
                {
                    "type": "text/html" if is_html else "text/plain",
                    "value": body,
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    json=payload,
                    headers=headers,
                )
            if resp.status_code >= 300:
                raise ProviderError(
                    f"SendGrid error {resp.status_code}: {resp.text}",
                    code="EMAIL_SENDGRID_ERROR",
                    details={"provider": "sendgrid", "status_code": resp.status_code},
                )
            return resp.headers.get("X-Message-Id", f"sg-{uuid.uuid4()}")
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"SendGrid HTTP error: {exc}",
                code="EMAIL_SENDGRID_HTTP_ERROR",
            ) from exc


class EmailService:
    """Provider-agnostic email service. Chosen at runtime via settings.email_provider."""

    def __init__(self) -> None:
        self.provider_name = settings.email_provider
        self._provider = self._build_provider(self.provider_name)

    def _build_provider(self, name: str):
        if name == "smtp":
            return _SMTPProvider()
        if name == "sendgrid":
            return _SendGridProvider()
        raise ProviderError(
            f"Unsupported email provider: {name}",
            code="EMAIL_PROVIDER_UNSUPPORTED",
        )

    def send(
        self,
        to: List[str],
        subject: str,
        body: str,
        is_html: bool = False,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> dict:
        """Send via configured provider. Returns the provider's response info.

        Raises ProviderError on failure (translated to HTTP 502 by the
        exception handler).
        """
        message_id = self._provider.send(to, subject, body, is_html, cc, bcc)
        return {
            "success": True,
            "message": "Email sent successfully",
            "provider": self._provider.name,
            "message_id": message_id,
        }


# Module-level singleton accessor (matches notification-svc original pattern).
# FastAPI Depends() wraps this via app/dependencies.py.
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Lazy singleton accessor."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
