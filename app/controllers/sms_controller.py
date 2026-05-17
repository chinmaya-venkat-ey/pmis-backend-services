"""SMSController — HTTP adapter for /notification/sms/send.

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\controllers\\sms_controller.py
(matching pattern; not re-read since structure is identical to email).
"""
from __future__ import annotations

from app.schemas.sms import SMSRequest, SMSResponse
from app.services.sms_service import SMSService


class SMSController:
    def __init__(self, service: SMSService):
        self.service = service

    def send(self, payload: SMSRequest) -> SMSResponse:
        result = self.service.send(
            to=payload.to,
            message=payload.message,
        )
        return SMSResponse(**result)
