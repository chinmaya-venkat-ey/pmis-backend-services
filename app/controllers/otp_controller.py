from app.schemas.otp import (
    OTPSendRequest,
    OTPSendResponse,
    OTPVerifyRequest,
    OTPVerifyResponse,
)
from app.services.otp_service import OTPService


class OTPController:
    def __init__(self, service: OTPService) -> None:
        self.service = service

    def send(self, payload: OTPSendRequest) -> OTPSendResponse:
        result = self.service.send_otp(
            channel=payload.channel,
            destination=payload.destination,
            purpose=payload.purpose or "verification",
        )
        return OTPSendResponse(**result)

    def verify(self, payload: OTPVerifyRequest) -> OTPVerifyResponse:
        result = self.service.verify_otp(
            channel=payload.channel,
            destination=payload.destination,
            otp=payload.otp,
        )
        return OTPVerifyResponse(**result)
