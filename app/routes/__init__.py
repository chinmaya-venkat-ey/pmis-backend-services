from fastapi import APIRouter

from app.config import settings
from app.routes.cron_routes import router as cron_router
from app.routes.dispatch_routes import router as dispatch_router
from app.routes.email_routes import router as email_router
from app.routes.health_routes import router as health_router
from app.routes.otp_routes import router as otp_router
from app.routes.sms_routes import router as sms_router

api_router = APIRouter(prefix=settings.api_prefix)
api_router.include_router(health_router)
api_router.include_router(email_router)
api_router.include_router(sms_router)
api_router.include_router(otp_router)
api_router.include_router(dispatch_router)
api_router.include_router(cron_router)
