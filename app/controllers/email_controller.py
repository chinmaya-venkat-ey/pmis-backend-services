from app.schemas.email import EmailRequest, EmailResponse
from app.services.email_service import EmailService


class EmailController:
    def __init__(self, service: EmailService) -> None:
        self.service = service

    def send_email(self, payload: EmailRequest) -> EmailResponse:
        result = self.service.send(
            to=[str(e) for e in payload.to],
            subject=payload.subject,
            body=payload.body,
            is_html=payload.is_html,
            cc=[str(e) for e in payload.cc] if payload.cc else None,
            bcc=[str(e) for e in payload.bcc] if payload.bcc else None,
        )
        return EmailResponse(**result)
