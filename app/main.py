"""pmis-masters-management — FastAPI app entry point.

Owns the `masters` Postgres schema (10 catalogs). All catalog routes are
RBAC-gated per Option C — `<catalog>:read` for reads, `<catalog>:manage`
for writes (see app/core/permissions.py for the full list).

Reads cross-schema:
  - users.* tables (RBAC hydration in AuthMiddleware)
  - project.projects, project.project_vendors (for /vendors/{id}/projects/list)

Never writes outside its own schema.
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
from app.routes import api_router
from app.routes.health_routes import router as health_router
from app.utilities.logger import configure_logging, get_logger


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "%s starting | env=%s",
        settings.service_name,
        settings.env,
    )
    yield
    logger.info("%s stopping", settings.service_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title="pmis-masters-management",
        version="0.1.0",
        description=(
            "PMIS Masters Service — catalog reference data: divisions, "
            "vendors (organizations), resource types, priorities, project "
            "categories, activity types/statuses, milestone statuses, "
            "project status transitions, notification templates. Granular "
            "per-catalog RBAC per Option C — every endpoint requires a "
            "`<catalog>:read` or `<catalog>:manage` permission code."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "PMIS Platform Team"},
        license_info={"name": "Proprietary"},
        root_path=settings.root_path,
        lifespan=lifespan,
    )

    # Middleware order (Starlette wraps LIFO — last add = outermost on inbound):
    #   1. CORSMiddleware  (outermost; only when ENV=development per Decision 8e)
    #   2. AuthMiddleware  (hydrates request.state.user_id + user_permissions)
    #   3. RequestContextMiddleware  (X-Request-ID + timing logs; innermost)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthMiddleware)
    if settings.env.lower() == "development":
        origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    app.include_router(api_router)    # /masters/*
    app.include_router(health_router)  # /health, /ready

    def _custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title, version=app.version,
            description=app.description, routes=app.routes,
            servers=[{"url": app.root_path}] if app.root_path else None,
        )
        schema.setdefault("components", {})["securitySchemes"] = {
            "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        }
        schema["security"] = [{"BearerAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi

    @app.get("/", tags=["root"], summary="Service info")
    def root() -> dict:
        return {
            "service": settings.service_name,
            "version": "0.1.0",
            "docs_url": f"{settings.root_path}/docs",
            "openapi_url": f"{settings.root_path}/openapi.json",
        }

    # Auto-wrap every successful response in the PMIS envelope. Health /
    # readiness probes stay as raw JSON so docker / k8s checks aren't
    # surprised by the envelope shape.
    install_hal_route_class(app, skip_paths={"/health", "/ready"})

    return app


app = create_app()
