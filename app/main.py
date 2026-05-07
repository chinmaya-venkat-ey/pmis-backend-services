"""pmis-user-service — FastAPI application entry point.

Self-contained: all auth logic (JWT, password hashing, RBAC, middleware)
lives inside this service. No external shared package.

Run locally:
    uvicorn app.main:app --reload --port 8001
"""
import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from .api import api_v3_router
from .core.config import settings
from .core.errors import DomainError, get_http_status
from .core.middleware import AuthenticationMiddleware, LoggingMiddleware
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
    logger.info("%s started on port 8001", settings.SERVICE_NAME)
    yield
    logger.info("%s shutting down", settings.SERVICE_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="PMIS user-management + authentication microservice.",
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
)


# ---- CORS + middleware order -------------------------------------------
# Starlette wraps LIFO: last add_middleware is OUTERMOST.
#
# Final order on requests (outermost → innermost):
#   1. CORSMiddleware (outermost) — handles OPTIONS preflights, stamps
#      Access-Control-Allow-* on every response. Must be outermost so
#      it sees responses from auth's early-return paths (revoked JTI,
#      pre-doc-26 integer user_id claim) and any future middleware
#      that short-circuits above it. Doc 39 lesson: CORS-as-innermost
#      strips headers on proxied / short-circuited responses and the
#      browser blocks them with "failed to fetch."
#   2. AuthenticationMiddleware — JWT decode + revoked-jti check +
#      effective-permissions hydration (incl. doc-41 scoped_permissions).
#   3. LoggingMiddleware (innermost) — request/response logs +
#      X-Request-Id stamping.
app.add_middleware(LoggingMiddleware)
app.add_middleware(AuthenticationMiddleware)
# CORS added LAST → outermost. See docstring above for why.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Exception handlers ------------------------------------------------

@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    status_code = get_http_status(exc)
    error_payload = format_error_response(
        error_type=exc.__class__.__name__,
        message=exc.message,
        details=exc.details,
    )
    return api_response(
        data=None, error=error_payload, message=None, status=status_code,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    error_payload = format_error_response(
        error_type="InternalError",
        message="An internal error occurred. Please try again later.",
        details={"error": str(exc)} if settings.DEBUG else None,
    )
    return api_response(
        data=None, error=error_payload, message=None,
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# ---- Routes ------------------------------------------------------------

app.include_router(api_v3_router)


# ---- OpenAPI: bearer auth on every non-public path ---------------------

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="PMIS user-management + authentication microservice.",
        routes=app.routes,
    )
    schema.setdefault("components", {})["securitySchemes"] = {
        "bearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT Bearer token. Obtain via /api/v3/users/login",
        }
    }
    public_paths = {
        "/health", "/",
        "/api/v3/users/login",
        "/api/v3/users/introspect",
        "/api/v3/users/refresh",
    }
    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method in {"get", "post", "put", "patch", "delete", "options", "head"}:
                if path not in public_paths:
                    operation.setdefault("security", [{"bearer": []}])
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


# ---- Health / root -----------------------------------------------------

@app.get("/health", tags=["health"])
def health() -> JSONResponse:
    """Liveness probe + SECRET_KEY hash prefix for ops verification.

    The hash prefix lets ops confirm this service shares the same
    SECRET_KEY as pmis-backend without ever exposing the secret itself.
    """
    key_digest = hashlib.sha256(settings.SECRET_KEY.encode()).hexdigest()[:12]
    return JSONResponse({
        "status": "ok",
        "service": settings.SERVICE_NAME,
        "version": settings.APP_VERSION,
        "secret_key_sha256_prefix": key_digest,
    })


@app.get("/", tags=["root"])
def root() -> JSONResponse:
    return JSONResponse({
        "_type": "Root",
        "_links": {
            "self": {"href": "/"},
            "users": {"href": "/api/v3/users"},
            "roles": {"href": "/api/v3/roles"},
            "login": {"href": "/api/v3/users/login"},
            "refresh": {"href": "/api/v3/users/refresh"},
            "introspect": {"href": "/api/v3/users/introspect"},
            "health": {"href": "/health"},
        },
        "instanceName": settings.APP_NAME,
        "version": settings.APP_VERSION,
    })
