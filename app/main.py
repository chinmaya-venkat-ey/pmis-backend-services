from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_context import RequestContextMiddleware
from app.routes import api_router
from app.routes.master_data_routes import router as master_data_router
from app.utilities.logger import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run init_db on startup so the template catalog is seeded."""
    try:
        from app.db.session import init_db
        init_db()
        logger.info("Database initialized.")
    except Exception as e:  # noqa: BLE001
        logger.error("init_db failed (continuing): %s", e)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=(
            "PIMS Notification Service — provides Email, SMS and OTP delivery "
            "endpoints for the PIMS platform. Providers and credentials are "
            "configured via environment variables (see `.env.example`).\n\n"
            "Doc 38 added the `/api/v3/master/notification_templates/*` "
            "admin surface (DB-backed template catalog, JWT-gated). The "
            "legacy `/api/v1/notifications/...` dispatch endpoints remain "
            "unauthenticated for back-compat."
        ),
        version="1.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "PIMS Platform Team"},
        license_info={"name": "Proprietary"},
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    # Doc 38: JWT decode + RBAC hydration on /api/v3/master/* endpoints.
    # The middleware is a no-op for /api/v1/notifications and /health.
    app.add_middleware(AuthMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router)
    # Doc 38: master-data router (notification_templates).
    app.include_router(master_data_router)

    @app.get("/", tags=["Root"], summary="Service info")
    def root() -> dict:
        return {
            "service": settings.app_name,
            "version": "1.1.0",
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
