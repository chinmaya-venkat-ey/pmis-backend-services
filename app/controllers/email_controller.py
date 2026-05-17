"""EmailController — HTTP adapter for /notification/email/send.

Per Q8: every resource has a thin controller layer between routes and
services. Controllers unpack the request model, call the service, and
shape the response.

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\controllers\\email_controller.py:1-19.
"""
from __future__ import annotations

from app.schemas.email import EmailRequest, EmailResponse
from app.services.email_service import EmailService


class EmailController:
    def __init__(self, service: EmailService):
        self.service = service

    def send(self, payload: EmailRequest) -> EmailResponse:
        result = self.service.send(
            to=[str(e) for e in payload.to],
            subject=payload.subject,
            body=payload.body,
            is_html=payload.is_html,
            cc=[str(e) for e in payload.cc] if payload.cc else None,
            bcc=[str(e) for e in payload.bcc] if payload.bcc else None,
        )
        return EmailResponse(**result)
