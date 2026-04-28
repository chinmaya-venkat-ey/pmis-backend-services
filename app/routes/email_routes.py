from fastapi import APIRouter, Depends, status

from app.controllers.email_controller import EmailController
from app.schemas.email import EmailRequest, EmailResponse
from app.services.email_service import EmailService, get_email_service

router = APIRouter(prefix="/notifications/email", tags=["Email Notifications"])


def get_controller(service: EmailService = Depends(get_email_service)) -> EmailController:
    return EmailController(service)


@router.post(
    "/send",
    response_model=EmailResponse,
    status_code=status.HTTP_200_OK,
    summary="Send an email notification",
    description="Sends an email through the provider configured in EMAIL_PROVIDER (smtp/sendgrid).",
)
def send_email(
    payload: EmailRequest,
    controller: EmailController = Depends(get_controller),
) -> EmailResponse:
    return controller.send_email(payload)
