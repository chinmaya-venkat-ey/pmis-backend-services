"""pmis-notification-management — FastAPI app entry point.

Stateless dispatcher post-Q3+Q13:
  - Owns no tables (notification_templates moved to masters per Q3;
    OTP storage moved to user-svc.otp_codes per Q13).
  - Reads masters.notification_templates and project.* / users.* cross-schema
    for template lookup (dispatch) and recipient resolution (daily-digest cron).

Routes:
  - POST /notification/email/send           (direct, server-to-server)
  - POST /notification/sms/send             (direct, server-to-server)
  - POST /notification/dispatch             (Doc-38 canonical templated dispatch)
  - POST /notification/cron/daily-digest    (X-Cron-Secret header)
  - GET  /health, /ready, /                 (orchestrator + service info)

No JWT auth middleware: every backend caller is on the docker-compose internal
network (trust boundary). The cron endpoint is gated by a shared-secret
header. If we ever add an admin endpoint here, add auth middleware then.

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\main.py:1-88
with these changes:
  - Removed AuthMiddleware (no JWT-required routes post-Q3).
  - Removed master_data_router (notification_templates moved to masters-svc).
  - Removed init_db() boot-time DDL (Q16: alembic runs separately on deploy).
  - Service prefix changed from /api/v1/notifications to /notification (PLAN.md §2.4).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_context import RequestContextMiddleware
from app.routes import api_router
from app.routes.health_routes import router as health_router
from app.utilities.logger import configure_logging, get_logger


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "%s starting | env=%s | email=%s | sms=%s",
        settings.service_name,
        settings.env,
        settings.email_provider,
        settings.sms_provider,
    )
    yield
    logger.info("%s stopping", settings.service_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title="pmis-notification-management",
        version="0.1.0",
        description=(
            "PMIS Notification Service — email/SMS dispatch + daily-digest cron. "
            "Stateless dispatcher (no owned tables post-refactor). Reads "
            "masters.notification_templates cross-schema for template render; "
            "scans users.* and project.* cross-schema for daily-digest recipients. "
            "Trust-boundary internal — no JWT (cron uses X-Cron-Secret header)."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "PMIS Platform Team"},
        license_info={"name": "Proprietary"},
        root_path=settings.root_path,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    # API surface under /notification (health/ready/root mounted at app root).
    app.include_router(api_router)
    app.include_router(health_router)

    @app.get("/", tags=["root"], summary="Service info")
    def root() -> dict:
        return {
            "service": settings.service_name,
            "version": "0.1.0",
            "docs_url": f"{settings.root_path}/docs",
            "openapi_url": f"{settings.root_path}/openapi.json",
        }

    return app


app = create_app()
