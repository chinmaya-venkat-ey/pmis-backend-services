"""JWT auth middleware for pmis-project-management.

Decodes the Bearer token, checks `users.revoked_tokens` cross-schema, then
hydrates request.state with user_id / permissions (flat + scoped) / is_admin.

Doc-41 scoped_permissions is essential here — project-svc's
`require_project_permission` reads it to compare against the path's
project_uuid.
"""
from __future__ import annotations

from typing import Set

from fastapi import Request
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import decode_access_token, extract_bearer_token
from app.db import SessionLocal
from app.repositories.rbac_read_repository import RbacReadRepository
from app.utilities.logger import get_logger


logger = get_logger(__name__)


_PUBLIC_PREFIXES = (
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    # Doc-35 dev fallback for attachment downloads. URLs are
    # UUID-guarded; the route is only mounted when
    # ``file_server_local_fallback_enabled`` is true.
    "/files",
)
_PUBLIC_EXACT = {"/"}


def _is_public_path(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    for prefix in _PUBLIC_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _set_anonymous(request: Request) -> None:
    request.state.user_id = None
    request.state.user_login = None
    request.state.user_email = None
    request.state.token_jti = None
    request.state.user_permissions = set()  # type: Set[str]
    request.state.scoped_permissions = {}
    request.state.is_admin = False


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        _set_anonymous(request)

        if _is_public_path(request.url.path):
            return await call_next(request)

        token = extract_bearer_token(request.headers.get("authorization"))
        if not token:
            return await call_next(request)

        claims = decode_access_token(token)
        if not claims:
            return await call_next(request)

        user_id = claims.get("user_id") or claims.get("sub")
        jti = claims.get("jti")
        if not user_id:
            return await call_next(request)

        db: Session = SessionLocal()
        try:
            rbac = RbacReadRepository(db)
            if jti and rbac.is_revoked(jti):
                return await call_next(request)

            perms: Set[str] = rbac.effective_permissions_for_user(user_id)
            scoped = rbac.effective_permissions_by_scope(user_id)
            is_admin: bool = rbac.is_admin(user_id)

            request.state.user_id = user_id
            request.state.user_login = claims.get("sub")
            request.state.user_email = claims.get("email")
            request.state.token_jti = jti
            request.state.user_permissions = perms
            request.state.scoped_permissions = scoped
            request.state.is_admin = is_admin
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auth hydration failed for user_id=%s: %s", user_id, exc)
        finally:
            db.close()

        return await call_next(request)
