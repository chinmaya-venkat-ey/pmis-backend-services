"""Templated dispatch service — combines template render + provider send.

POST /notification/dispatch is the single canonical endpoint internal callers
(user-svc, etc.) use to fire a templated notification by `template_kind`.
notification-svc owns the catalog (cross-schema masters.notification_templates
per Q3) and the render logic; callers send only the dispatch intent + payload.

Logic ported from the inline route handler in
  C:\\Programming\\PMIS\\PMIS-notification-service\\app\\routes\\dispatch_routes.py:38-67
factored into a service class per Q8 (controllers + services in every service).
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.services.email_service import EmailService
from app.services.sms_service import SMSService
from app.services.template_service import TemplateService


class DispatchService:
    """Orchestrates template lookup + render + provider send."""

    def __init__(
        self,
        db: Session,
        email_service: EmailService,
        sms_service: SMSService,
    ):
        self.db = db
        self.email_service = email_service
        self.sms_service = sms_service
        self.template_service = TemplateService(db)

    def dispatch(
        self,
        *,
        channel: str,
        recipient: str,
        template_kind: str,
        payload: Dict[str, Any],
    ) -> dict:
        """Render the template for (channel, template_kind) and send via the
        configured provider. Returns the full DispatchResponse payload as a dict.

        Channel is validated by the request schema as Literal["email","sms"].
        """
        if channel == "email":
            subject, body, is_html = self.template_service.render_email(
                template_kind, payload
            )
            result = self.email_service.send(
                to=[recipient],
                subject=subject,
                body=body,
                is_html=is_html,
            )
            return {
                **result,
                "channel": "email",
                "template_kind": template_kind,
                "rendered_subject": subject,
            }

        # channel == "sms" (the request schema rejects anything else)
        message = self.template_service.render_sms(template_kind, payload)
        result = self.sms_service.send(to=recipient, message=message)
        return {
            **result,
            "channel": "sms",
            "template_kind": template_kind,
            "rendered_subject": None,
        }
