"""POST /notification/sms/send — direct (non-templated) SMS dispatch.

Trust-boundary internal endpoint: no JWT auth.

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\routes\\sms_routes.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.controllers.sms_controller import SMSController
from app.dependencies import get_sms_controller
from app.schemas.sms import SMSRequest, SMSResponse


router = APIRouter(prefix="/sms", tags=["sms"])


@router.post(
    "/send",
    response_model=SMSResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a direct (non-templated) SMS",
    description=(
        "Dispatches an SMS via the configured provider (mock/twilio/msg91). "
        "Intended for server-to-server callers that already have a rendered "
        "message. For templated dispatch, use POST /notification/dispatch instead."
    ),
)
def send_sms(
    payload: SMSRequest,
    controller: Annotated[SMSController, Depends(get_sms_controller)],
) -> SMSResponse:
    return controller.send(payload)
