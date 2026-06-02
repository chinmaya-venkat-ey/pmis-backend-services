"""pmis-user-management — FastAPI application entry point.

Mounts:
  - Business routers under ``/user/*`` (auth, users, roles, permissions,
    role-assignments, role-grants).
  - Health probes (``/health``, ``/ready``) at the app root.

Middleware order (outermost → innermost):
  1. CORSMiddleware  — dev only (Decision 8e)
  2. RequestContextMiddleware  — assigns request_id, logs in/out
  3. AuthMiddleware  — decodes JWT, hydrates request.state

UNIVERSAL_OTP_ENABLED=true activates the break-glass OTP backdoor (000000).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.config import settings
from app.core.api_route import install_hal_route_class
from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_context import RequestContextMiddleware
from app.routes import health_routes, user_router
from app.utilities.logger import configure_logging, get_logger


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.universal_otp_enabled:
        logger.warning("UNIVERSAL_OTP_ENABLED=true — universal OTP backdoor is active")
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_routes.router)
    app.include_router(user_router)

    def _custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title, version=app.version,
            description=app.description, routes=app.routes,
        )
        schema.setdefault("components", {})["securitySchemes"] = {
            "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        }
        schema["security"] = [{"BearerAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi

    @app.get("/", tags=["root"], summary="Service info")
    async def root():
        return {
            "service": settings.service_name,
            "version": "0.1.0",
            "docs_url": f"{settings.root_path}/docs",
        }

    # Auto-wrap every successful response in the PMIS envelope. Health /
    # readiness probes stay as raw JSON so docker / k8s checks aren't
    # surprised by the envelope shape.
    install_hal_route_class(app, skip_paths={"/health", "/ready"})

    return app


app = create_app()
