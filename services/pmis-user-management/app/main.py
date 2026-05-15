"""pmis-user-management — FastAPI application entry point.

Mounts:
  - Business routers under ``/user/*`` (auth, users, roles, permissions,
    role-assignments, role-grants).
  - Health probes (``/health``, ``/ready``) at the app root.

Middleware order (outermost → innermost):
  1. CORSMiddleware  — dev only (Decision 8e)
  2. RequestContextMiddleware  — assigns request_id, logs in/out
  3. AuthMiddleware  — decodes JWT, hydrates request.state

Q14: refuses to boot if ``UNIVERSAL_OTP_ENABLED=true`` in production.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_context import RequestContextMiddleware
from app.routes import health_routes, user_router
from app.utilities.logger import configure_logging, get_logger


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Q14: hard-fail if UNIVERSAL_OTP_ENABLED is True in production.
    if settings.env == "production" and settings.universal_otp_enabled:
        raise RuntimeError(
            "UNIVERSAL_OTP_ENABLED must be False in production (Q14). "
            "Refusing to start with the break-glass OTP backdoor enabled."
        )
    logger.info(
        "Starting %s | env=%s | notification_client=%s",
        settings.service_name, settings.env, settings.notification_client,
    )
    yield
    logger.info("Stopping %s", settings.service_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title="pmis-user-management",
        version="0.1.0",
        description=(
            "User, auth, RBAC, OTP, password-reset, role-assignments. "
            "Owns the `users` schema; reads cross-schema mirrors of "
            "`masters.vendors`, `masters.divisions`, `project.projects`, "
            "`project.project_vendors`."
        ),
        root_path=settings.root_path,
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    # Middleware are applied bottom-up: the last `add_middleware` call is the
    # OUTERMOST layer. So the actual on-the-wire order ends up as:
    #   CORS → RequestContext → Auth → route handler
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestContextMiddleware)
    if settings.env == "development":
        origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(health_routes.router)
    app.include_router(user_router)

    @app.get("/", tags=["root"], summary="Service info")
    async def root():
        return {
            "service": settings.service_name,
            "version": "0.1.0",
            "docs_url": f"{settings.root_path}/docs",
        }

    return app


app = create_app()
