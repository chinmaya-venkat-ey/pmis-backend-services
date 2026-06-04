"""JWT auth middleware for pmis-user-management.

Decodes the Bearer token, checks `users.revoked_tokens` (this service OWNS
that table — no cross-schema), then hydrates request.state with:
  - user_id          : str (None for anonymous requests)
  - user_login       : Optional[str]
  - user_email       : Optional[str]
  - token_jti        : Optional[str]
  - user_permissions : Set[str]  (flat union of role + direct grants)
  - scoped_permissions : Dict[(kind, id), Set[str]]  (Doc-41 scope tiers)
  - is_admin         : bool
  - vendor_id        : Optional[str]  (caller's owning vendor/organization;
                       NULL for users with no vendor affiliation. Bug #174:
                       must be hydrated so non-admin user-list callers are
                       scoped to their own vendor.)

Anonymous-passthrough: requests with no/invalid/revoked token leave
request.state anonymous and the route's require_* dep decides what to do.

Public-path allow-list bypasses the JWT path entirely for: health endpoints,
login, refresh, OTP routes, forgot/reset-password, introspect, /docs etc.
"""
from __future__ import annotations

from typing import Set

from fastapi import Request
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import decode_access_token, extract_bearer_token
from app.db import SessionLocal
from app.repositories.rbac_repository import RbacRepository
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# Endpoints that bypass the JWT path entirely.
_PUBLIC_PREFIXES = (
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
)
_PUBLIC_EXACT = {
    "/",
    # Auth endpoints — anonymous by design
    "/api/v3/users/login",
    "/api/v3/users/refresh",
    "/api/v3/users/introspect",
    "/api/v3/users/login/send-otp",
    "/api/v3/users/login/verify-otp",
    "/api/v3/users/forgot-password",
    "/api/v3/users/reset-password",
}


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
    request.state.vendor_id = None


class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that hydrates request.state from the JWT."""

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

        # Doc-26 guard dropped per Q17 — pre-Doc-26 int-id tokens are
        # already past their 7-day refresh window by the time this lands.

        db: Session = SessionLocal()
        try:
            rbac = RbacRepository(db)
            if jti and rbac.is_revoked(jti):
                # Revoked — stay anonymous.
                return await call_next(request)

            perms: Set[str] = rbac.effective_permissions_for_user(user_id)
            scoped = rbac.effective_permissions_by_scope(user_id)
            is_admin: bool = rbac.user_has_admin_role(user_id)
            # Bug #174: hydrate vendor_id so the user-list endpoint can
            # scope non-admin callers to their own vendor/organization.
            # One pure-PK lookup; cheap.
            from app.models.user import User as _UserModel
            user_row = db.get(_UserModel, user_id)
            vendor_id = getattr(user_row, "vendor_id", None) if user_row else None

            request.state.user_id = user_id
            request.state.user_login = claims.get("sub")
            request.state.user_email = claims.get("email")
            request.state.token_jti = jti
            request.state.user_permissions = perms
            request.state.scoped_permissions = scoped
            request.state.is_admin = is_admin
            request.state.vendor_id = vendor_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auth hydration failed for user_id=%s: %s", user_id, exc)
            # Anonymous defaults stay in place; route dep emits 401.
        finally:
            db.close()

        return await call_next(request)
