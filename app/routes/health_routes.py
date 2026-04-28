from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Service health check")
def health() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "env": settings.app_env,
        "email_provider": settings.email_provider,
        "sms_provider": settings.sms_provider,
    }
