from fastapi import APIRouter, Depends, status

from app.controllers.sms_controller import SMSController
from app.schemas.sms import SMSRequest, SMSResponse
from app.services.sms_service import SMSService, get_sms_service

router = APIRouter(prefix="/notifications/sms", tags=["SMS Notifications"])


def get_controller(service: SMSService = Depends(get_sms_service)) -> SMSController:
    return SMSController(service)


@router.post(
    "/send",
    response_model=SMSResponse,
    status_code=status.HTTP_200_OK,
    summary="Send an SMS notification",
    description="Sends an SMS through the provider configured in SMS_PROVIDER (twilio/msg91/mock).",
)
def send_sms(
    payload: SMSRequest,
    controller: SMSController = Depends(get_controller),
) -> SMSResponse:
    return controller.send_sms(payload)
