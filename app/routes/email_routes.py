"""POST /notification/email/send — direct (non-templated) email dispatch.

Trust-boundary internal endpoint: no JWT auth (network-bounded; the FE
should never call this directly — it calls /notification/dispatch via
user-svc instead).

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\routes\\email_routes.py:1-26.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.controllers.email_controller import EmailController
from app.dependencies import get_email_controller
from app.schemas.email import EmailRequest, EmailResponse


router = APIRouter(prefix="/email", tags=["email"])


@router.post(
    "/send",
    response_model=EmailResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a direct (non-templated) email",
    description=(
        "Dispatches an email via the configured provider (smtp/sendgrid). "
        "Intended for server-to-server callers that already have rendered "
        "subject + body. For templated dispatch (FE / OTP / password reset), "
        "use POST /notification/dispatch instead."
    ),
)
def send_email(
    payload: EmailRequest,
    controller: EmailController = Depends(get_email_controller),
) -> EmailResponse:
    return controller.send(payload)
