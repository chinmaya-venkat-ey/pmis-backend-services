"""Templated dispatch route (doc 38 phase 2).

POST /api/v1/notifications/dispatch — accepts ``{channel, recipient,
template_kind, payload}``, looks up the active template row, renders it,
and forwards to the provider via the existing email/sms services.

Lets callers send a single HTTP request instead of fetching the template
+ rendering + dispatching separately. Server-side rendering also
guarantees every consumer sees the same body for the same template,
even when the catalog is updated.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dispatch import DispatchRequest, DispatchResponse
from app.services.email_service import EmailService, get_email_service
from app.services.sms_service import SMSService, get_sms_service
from app.services.template_service import render_email, render_sms


router = APIRouter(prefix="/notifications", tags=["Templated Dispatch"])


@router.post(
    "/dispatch",
    response_model=DispatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Render a template and dispatch via the configured provider",
    description=(
        "Single-call alternative to fetching a template + rendering + "
        "calling /email/send or /sms/send. Used by user-mgmt's auth "
        "flows so it never has to host a template renderer."
    ),
)
def dispatch_templated(
    payload: DispatchRequest,
    db: Session = Depends(get_db),
    email_service: EmailService = Depends(get_email_service),
    sms_service: SMSService = Depends(get_sms_service),
) -> DispatchResponse:
    if payload.channel == "email":
        subject, body, is_html = render_email(
            db, payload.template_kind, payload.payload,
        )
        result = email_service.send(
            to=[payload.recipient],
            subject=subject,
            body=body,
            is_html=is_html,
        )
        return DispatchResponse(
            **result,
            channel="email",
            template_kind=payload.template_kind,
            rendered_subject=subject,
        )
    # channel == "sms" (validated by Literal in the schema)
    message = render_sms(db, payload.template_kind, payload.payload)
    result = sms_service.send(to=payload.recipient, message=message)
    return DispatchResponse(
        **result,
        channel="sms",
        template_kind=payload.template_kind,
    )
