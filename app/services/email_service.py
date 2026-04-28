import smtplib
import ssl
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.utilities.logger import get_logger

logger = get_logger(__name__)


class EmailProviderError(Exception):
    pass


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
                context = ssl.create_default_context()
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=context)
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
            raise EmailProviderError(f"SMTP send failed: {exc}") from exc

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
            raise EmailProviderError("SENDGRID_API_KEY is not configured")

        personalization = {"to": [{"email": e} for e in to]}
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
                raise EmailProviderError(
                    f"SendGrid error {resp.status_code}: {resp.text}"
                )
            return resp.headers.get("X-Message-Id", f"sg-{uuid.uuid4()}")
        except httpx.HTTPError as exc:
            raise EmailProviderError(f"SendGrid HTTP error: {exc}") from exc


class EmailService:
    """Provider-agnostic email service. Provider chosen at runtime via env."""

    def __init__(self) -> None:
        self.provider_name = settings.email_provider
        self._provider = self._build_provider(self.provider_name)

    def _build_provider(self, name: str):
        if name == "smtp":
            return _SMTPProvider()
        if name == "sendgrid":
            return _SendGridProvider()
        raise EmailProviderError(f"Unsupported email provider: {name}")

    def send(
        self,
        to: List[str],
        subject: str,
        body: str,
        is_html: bool = False,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> dict:
        try:
            message_id = self._provider.send(to, subject, body, is_html, cc, bcc)
            return {
                "success": True,
                "message": "Email sent successfully",
                "provider": self._provider.name,
                "message_id": message_id,
            }
        except EmailProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            )


_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
