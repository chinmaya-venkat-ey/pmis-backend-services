"""pmis-file-store — FastAPI application entry point.

Mounts:
  - /api/v3/files/*         — file CRUD, upload, download, audit-log routes
  - /health  /ready         — probes (raw JSON, not wrapped)

Middleware order (outermost → innermost, added bottom-up):
  1. CORSMiddleware
  2. RequestContextMiddleware
  3. AuthMiddleware
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
from app.routes import files_router
from app.routes.health_routes import router as health_router
from app.utilities.logger import configure_logging, get_logger
from app.utilities.s3_client import get_s3_client


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s | env=%s", settings.service_name, settings.env)

    # Fail-fast S3 probe. A broken S3 config is better caught at boot than on
    # the first upload. We log a warning instead of aborting so health routes
    # remain reachable and the issue is surfaced via /ready.
    try:
        ok = get_s3_client().health_check()
        if ok:
            logger.info("S3 connectivity probe: OK | bucket=%s", settings.s3_bucket_name)
        else:
            logger.warning(
                "S3 connectivity probe: FAILED (bucket=%s). "
                "Uploads will return 503 until S3 is reachable.",
                settings.s3_bucket_name,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("S3 connectivity probe raised: %s", exc)

    yield
    logger.info("Stopping %s", settings.service_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title="pmis-file-store",
        version="1.0.0",
        description=(
            "Centralised file storage microservice for the PMIS platform. "
            "Stores files in AWS S3 (or S3-compatible backends like MinIO). "
            "Provides upload, download (pre-signed URLs), search, soft-delete, "
            "restore, and audit-log endpoints. "
            "Owns the `files` schema; reads cross-schema users.* for RBAC. "
            "Replaces the NFS-backed attachment storage used in earlier services."
        ),
        root_path=settings.root_path,
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    # Bottom-up: last add = outermost.
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(files_router)

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
            "version": "1.0.0",
            "docs_url": f"{settings.root_path}/docs",
        }

    install_hal_route_class(app, skip_paths={"/health", "/ready"})
    return app


app = create_app()
