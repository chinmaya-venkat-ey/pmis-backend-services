"""JWT auth middleware for pmis-masters-management.

Decodes the Bearer token, checks `users.revoked_tokens` cross-schema for
the token's jti, then hydrates request.state with:
  - user_id          : str (None for anonymous requests)
  - user_login       : Optional[str]
  - user_email       : Optional[str]
  - token_jti        : Optional[str]
  - user_permissions : Set[str]  (flat union of role + direct grants)
  - is_admin         : bool

Anonymous-passthrough: requests with no/invalid/revoked token are NOT
short-circuited at the middleware. Instead, request.state stays anonymous
and the route's `require_*` dependency (in app/core/rbac.py) decides
what to do — returning 401 / 403 only when the route actually needs auth.
This keeps /health, /ready, / open without per-route override.

Public-path allow-list: middleware skips the JWT path entirely for
endpoints that are public by design. See `_PUBLIC_PREFIXES` below.

WARNING: This middleware needs to match the JWT-issuance pattern in
pmis-user-management. The shared `SECRET_KEY` and `algorithm` settings
must agree across services (Decision 7).
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


# Endpoints that bypass the JWT path entirely. Mirror the monolith convention.
_PUBLIC_PREFIXES = (
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
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
    request.state.user_vendor_id = None  # Round-7: hydrated below from users.users mirror
    request.state.is_admin = False


class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that hydrates request.state from the JWT."""

    async def dispatch(self, request: Request, call_next):
        # Always start anonymous; the route dep enforces what's required.
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

        # DB lookups for revoked-token check + permission hydration.
        # Middleware uses SessionLocal() directly because it runs before
        # FastAPI dependency resolution.
        db: Session = SessionLocal()
        try:
            rbac = RbacReadRepository(db)
            if jti and rbac.is_revoked(jti):
                # Token was logged-out / revoked. Stay anonymous; the route
                # dep will issue 401.
                return await call_next(request)

            perms: Set[str] = rbac.effective_permissions_for_user(user_id)
            is_admin: bool = rbac.is_admin(user_id)

            request.state.user_id = user_id
            request.state.user_login = claims.get("sub")
            request.state.user_email = claims.get("email")
            request.state.token_jti = jti
            request.state.user_permissions = perms
            request.state.is_admin = is_admin

            # Round-7: hydrate the caller's vendor_id for VendorService's
            # row-level scoping. Cheap PK lookup against the users.users mirror.
            from app.models._cross_schema import User as MirrorUser

            mirror_row = db.get(MirrorUser, user_id)
            if mirror_row is not None:
                request.state.user_vendor_id = mirror_row.vendor_id
        except Exception as exc:  # noqa: BLE001 — never crash the request on RBAC lookup
            logger.warning("Auth hydration failed for user_id=%s: %s", user_id, exc)
            # Leave anonymous defaults in place; route dep emits 401.
        finally:
            db.close()

        return await call_next(request)
