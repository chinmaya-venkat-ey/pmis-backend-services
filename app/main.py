"""FastAPI application entry point for pmis-project-service."""
import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi

from .api.router import api_v3_router
from .core.config import settings
from .core.errors import DomainError, get_http_status
from .core.middleware.auth import AuthenticationMiddleware
from .core.middleware.logging import LoggingMiddleware
from .infrastructure.db.session import init_db


logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="PMIS Project Management Service",
)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Starting %s v%s...", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized successfully")
    logger.info("%s started on port 8003", settings.SERVICE_NAME)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("%s shutting down", settings.SERVICE_NAME)


# ---- Middleware --------------------------------------------------------

app.add_middleware(LoggingMiddleware)
app.add_middleware(AuthenticationMiddleware)


# ---- Exception handlers -----------------------------------------------

@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Map all domain errors to the HAL+JSON envelope shape."""
    status = get_http_status(exc)
    body = {
        "data": None,
        "message": None,
        "error": {
            "_type": "Error",
            "errorIdentifier": type(exc).__name__,
            "message": exc.message,
        },
        "status": status,
    }
    if exc.details:
        body["error"]["_embedded"] = {"details": exc.details}
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic validation failures → 422 with FastAPI's default detail.

    `jsonable_encoder` is required because Pydantic 2.x error dicts can
    embed the originating Python exception object (under ``ctx.error``)
    when a field_validator raised ``ValueError(...)``. Plain ``json.dumps``
    chokes on that — encoder coerces it to a string.
    """
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors())},
    )


# ---- Routes ------------------------------------------------------------

app.include_router(api_v3_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.get("/", tags=["health"])
async def root() -> dict:
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
    }


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
        },
    }
    public = {"/", "/health", "/docs", "/redoc", "/openapi.json"}
    for path, methods in schema.get("paths", {}).items():
        if path in public:
            continue
        for method in methods.values():
            method.setdefault("security", [{"bearer": []}])
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
