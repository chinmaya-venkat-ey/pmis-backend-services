"""FastAPI application entry point for pmis-project-service."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from .api.router import api_v3_router
from .core.config import settings
from .core.errors import DomainError, get_http_status
from .core.middleware.auth import AuthenticationMiddleware
from .core.middleware.logging import LoggingMiddleware
from .core.response import api_response, format_error_response
from .infrastructure.db.session import init_db


logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s...", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized successfully")
    logger.info("%s started", settings.SERVICE_NAME)
    yield
    logger.info("%s shutting down", settings.SERVICE_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="PMIS Project Management Service",
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
)

# ---- Middleware --------------------------------------------------------
# Reverse-order add: Auth runs first, then Logging.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(AuthenticationMiddleware)


# ---- Exception handlers -----------------------------------------------

@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    status_code = get_http_status(exc)
    error_payload = format_error_response(
        error_type=exc.__class__.__name__,
        message=exc.message,
        details=exc.details,
    )
    return api_response(
        data=None,
        error=error_payload,
        message=None,
        status=status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    error_payload = format_error_response(
        error_type="InternalError",
        message="An internal error occurred. Please try again later.",
        details={"error": str(exc)} if settings.DEBUG else None,
    )
    return api_response(
        data=None,
        error=error_payload,
        message=None,
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# ---- Routes ------------------------------------------------------------

app.include_router(api_v3_router)


# ---------------------------------------------------------------------------
# Doc 35: local fallback file route.
#
# Comment rows store an attachment URL directly. When the deployment hasn't
# configured FILE_SERVER_PUBLIC_BASE_URL (typical for dev), the stored URL
# is a relative storage_key and the FE expects the BE to serve the bytes
# itself. This route provides exactly that fallback. Disabled by setting
# FILE_SERVER_LOCAL_FALLBACK_ENABLED=False once a real external file server
# is reachable from the FE directly.
# ---------------------------------------------------------------------------
if settings.FILE_SERVER_LOCAL_FALLBACK_ENABLED:
    from urllib.parse import quote

    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse

    from .infrastructure.storage import StorageUnavailableError, get_storage

    @app.get(
        "/files/{storage_key:path}",
        tags=["files"],
        summary="Doc 35: local fallback that streams attachment file bytes",
    )
    def serve_local_file(storage_key: str):
        """Stream bytes for an attachment stored on the local FileStorage.

        Auth-free by design — URLs are unguessable (UUID-prefixed) and
        the route mounts only when ``FILE_SERVER_LOCAL_FALLBACK_ENABLED``
        is true.
        """
        storage = get_storage()
        try:
            stream = storage.open(storage_key)
        except StorageUnavailableError:
            raise HTTPException(status_code=404, detail="File not found.")

        suggested_name = storage_key.rsplit("/", 1)[-1]
        if "_" in suggested_name:
            suggested_name = suggested_name.split("_", 1)[1] or suggested_name

        def chunk_iter():
            try:
                while True:
                    chunk = stream.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                stream.close()

        safe = quote(suggested_name)
        return StreamingResponse(
            chunk_iter(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": (
                    f'inline; filename="{suggested_name}"; '
                    f"filename*=UTF-8''{safe}"
                ),
            },
        )


# ---- OpenAPI: bearer auth on every non-public path --------------------

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="PMIS project-management microservice.",
        routes=app.routes,
    )
    schema.setdefault("components", {})["securitySchemes"] = {
        "bearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT Bearer token (minted by user-service)",
        },
    }
    # Public paths — auth surface lives on user-service. /files is the
    # local-fallback attachment route; auth on it would break FE rendering.
    public_paths = {"/", "/health", "/docs", "/redoc", "/openapi.json", "/files/{storage_key}"}
    for path, methods in schema.get("paths", {}).items():
        if path in public_paths:
            continue
        for method, operation in methods.items():
            if method in ("get", "post", "put", "patch", "delete", "options", "head", "trace"):
                operation.setdefault("security", [{"bearer": []}])
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


# ---- Health + root -----------------------------------------------------

@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """Health check.

    Reports service status and file-storage backend reachability. Auth
    + notification subsystems live on user-service.
    """
    from .infrastructure.storage import get_storage

    storage_healthy = False
    try:
        storage_healthy = get_storage().is_healthy()
    except Exception:
        storage_healthy = False

    return {
        "_type": "Health",
        "status": "healthy",
        "service": settings.SERVICE_NAME,
        "version": settings.APP_VERSION,
        "storage": {
            "healthy": storage_healthy,
            "base_path": settings.ATTACHMENTS_STORAGE_BASE_PATH,
            "nfs_server": settings.ATTACHMENTS_NFS_SERVER or None,
            "nfs_export": settings.ATTACHMENTS_NFS_EXPORT or None,
            "max_bytes": settings.ATTACHMENTS_MAX_BYTES,
        },
    }


@app.get("/", tags=["root"])
async def root() -> dict:
    return {
        "_type": "Root",
        "_links": {"self": {"href": "/"}},
        "service": settings.SERVICE_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
    }
