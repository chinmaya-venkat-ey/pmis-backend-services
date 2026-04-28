from fastapi import APIRouter, Depends, status

from app.controllers.otp_controller import OTPController
from app.schemas.otp import (
    OTPSendRequest,
    OTPSendResponse,
    OTPVerifyRequest,
    OTPVerifyResponse,
)
from app.services.otp_service import OTPService, get_otp_service

router = APIRouter(prefix="/notifications/otp", tags=["OTP Service"])


def get_controller(service: OTPService = Depends(get_otp_service)) -> OTPController:
    return OTPController(service)


@router.post(
    "/send",
    response_model=OTPSendResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate and send an OTP via SMS or Email",
    description="Generates a numeric OTP and delivers it through the chosen channel.",
)
def send_otp(
    payload: OTPSendRequest,
    controller: OTPController = Depends(get_controller),
) -> OTPSendResponse:
    return controller.send(payload)


@router.post(
    "/verify",
    response_model=OTPVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify a previously sent OTP",
)
def verify_otp(
    payload: OTPVerifyRequest,
    controller: OTPController = Depends(get_controller),
) -> OTPVerifyResponse:
    return controller.verify(payload)
