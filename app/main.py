"""pmis-project-management — FastAPI application entry point.

Mounts:
  - Business routers under ``/project/*`` (projects, milestones, activities,
    tasks, subtasks, comments).
  - Health probes (``/health``, ``/ready``) at the app root.

Middleware order (outermost → innermost):
  1. CORSMiddleware  — dev only (Decision 8e)
  2. RequestContextMiddleware  — assigns request_id, logs in/out
  3. AuthMiddleware  — decodes JWT, hydrates request.state including Doc-41
                       scoped_permissions for require_project_permission
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
from app.routes import attachment_routes, health_routes, project_router
from app.utilities.file_client import get_file_client
from app.utilities.logger import configure_logging, get_logger


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s | env=%s",
        settings.service_name, settings.env,
    )

    # Fail-fast probe on attachment storage. In prod the base path is an
    # NFS mount (10.1.131.199); if it's missing / unmounted / read-only we
    # want to know at startup, not on the first upload. In dev the base
    # path may simply not be configured yet — log a warning but don't
    # block app boot, since /health and the non-attachment routes still
    # work fine.
    try:
        get_file_client()._storage.ensure_ready()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — startup must remain best-effort
        logger.warning(
            "Attachment storage probe failed at startup: %s. "
            "Uploads will return 503 until the storage backend is reachable.",
            exc,
        )

    yield
    logger.info("Stopping %s", settings.service_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title="pmis-project-management",
        version="0.1.0",
        description=(
            "Projects, milestones, activities, tasks, subtasks, comments. "
            "Owns the `project` schema; reads cross-schema mirrors of "
            "`users.*` (auth + RBAC) and `masters.*` (vendors, divisions, "
            "priorities, statuses, transitions, resource types)."
        ),
        root_path=settings.root_path,
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    # Bottom-up registration: the last add_middleware is the OUTERMOST layer.
    # On-the-wire order: CORS → RequestContext → Auth → route handler.
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
    app.include_router(project_router)
    # Dev-only fallback for serving attachment bytes when no external
    # file server is configured. Mounted at the app root (not under
    # /project) so the public URL matches the prefix shape used in prod.
    if settings.file_server_local_fallback_enabled:
        app.include_router(attachment_routes.files_router)

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
