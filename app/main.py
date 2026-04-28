from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_context import RequestContextMiddleware
from app.routes import api_router
from app.utilities.logger import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=(
            "PIMS Notification Service — provides Email, SMS and OTP delivery "
            "endpoints for the PIMS platform. Providers and credentials are "
            "configured via environment variables (see `.env.example`)."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "PIMS Platform Team"},
        license_info={"name": "Proprietary"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/", tags=["Root"], summary="Service info")
    def root() -> dict:
        return {
            "service": settings.app_name,
            "version": "1.0.0",
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    logger.info(
        "%s started | env=%s | email=%s | sms=%s",
        settings.app_name,
        settings.app_env,
        settings.email_provider,
        settings.sms_provider,
    )
    return app


app = create_app()
