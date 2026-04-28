from app.schemas.sms import SMSRequest, SMSResponse
from app.services.sms_service import SMSService


class SMSController:
    def __init__(self, service: SMSService) -> None:
        self.service = service

    def send_sms(self, payload: SMSRequest) -> SMSResponse:
        result = self.service.send(to=payload.to, message=payload.message)
        return SMSResponse(**result)
