"""Auth middleware (doc 38).

Decodes the Bearer token on every request, hydrates
``request.state.user_id`` / ``user_login`` / ``user_permissions`` /
``is_admin`` / ``token_jti`` from the shared Postgres. Identical
contract to the monolith and user-service auth middleware so route
decorators can use the same ``require_permission(code)`` pattern.

Public paths (everything under ``/api/v1/notifications`` and
``/health`` and ``/`` and ``/docs``) skip the auth check — they're
internal contracts called from inside the trust boundary.

Protected paths (``/api/v3/master/*``) require a valid Bearer token
and a permission check via ``require_permission(...)``.
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ..core.auth import decode_access_token
from ..db.repositories.rbac_read_repository import RbacReadRepository
from ..db.session import SessionLocal


logger = logging.getLogger(__name__)


# Paths that bypass auth entirely. Order matters — most specific first.
_PUBLIC_PREFIXES = (
    "/api/v1/notifications",   # legacy dispatch endpoints — internal trust boundary
    "/api/v1/health",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
)


def _is_public_path(path: str) -> bool:
    for p in _PUBLIC_PREFIXES:
        if path == p or path.startswith(p + "/") or path.startswith(p + "?"):
            return True
    return path == "/"


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Default to anonymous request state.
        request.state.user_id = None
        request.state.user_login = None
        request.state.user_email = None
        request.state.token_jti = None
        request.state.user_permissions = set()
        request.state.is_admin = False

        path = request.url.path
        if _is_public_path(path):
            return await call_next(request)

        # Extract bearer token.
        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return await call_next(request)
        token = auth_header[7:].strip()
        claims = decode_access_token(token)
        if not claims:
            return await call_next(request)

        user_id = claims.get("user_id")
        # Pre-doc-26 integer-id JWTs would not be UUID-shape; reject those
        # silently (downstream require_permission returns 401).
        if not isinstance(user_id, str) or not user_id:
            return await call_next(request)

        # Hydrate from shared Postgres.
        db = SessionLocal()
        try:
            repo = RbacReadRepository(db)
            jti = claims.get("jti")
            if jti and repo.is_revoked(jti):
                # Treat revoked tokens as anonymous.
                return await call_next(request)
            request.state.user_id = user_id
            request.state.user_login = claims.get("sub")
            request.state.user_email = claims.get("email")
            request.state.token_jti = jti
            request.state.user_permissions = repo.effective_permissions_for_user(user_id)
            request.state.is_admin = repo.is_admin(user_id)
        except Exception as e:  # noqa: BLE001
            logger.error("Auth middleware DB lookup failed: %s", e)
            # Stay anonymous; downstream returns 401.
        finally:
            db.close()
        return await call_next(request)


# ---------------------------------------------------------------------------
# require_permission — FastAPI dependency
# ---------------------------------------------------------------------------

from fastapi import Depends, HTTPException, status
from starlette.requests import Request as StarletteRequest


def require_permission(code: str):
    """Returns a FastAPI dependency that gates the route on a permission code."""

    def _checker(request: StarletteRequest) -> None:
        user_id = getattr(request.state, "user_id", None)
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "errorIdentifier": "AuthenticationError",
                    "message": "Authentication required",
                },
            )
        perms = getattr(request.state, "user_permissions", set())
        if code not in perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "errorIdentifier": "AuthorizationError",
                    "message": f"Insufficient permissions. Required: {code}",
                },
            )

    return Depends(_checker)
