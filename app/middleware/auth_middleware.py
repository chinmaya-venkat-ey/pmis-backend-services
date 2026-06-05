"""Auth middleware for pmis-masters-management — pure Policy Enforcement Point.

Forwards the caller's ``Authorization`` header to user-management's
``GET /api/v3/authz/context`` and hydrates ``request.state`` from the decided
context. This service no longer resolves permissions from ``users.*`` itself —
the old cross-schema ``RbacReadRepository`` (and its §3.3 / C5 drift) is gone.

Anonymous-passthrough: a request with no/invalid/revoked token leaves
request.state anonymous and the route's ``require_*`` dependency decides
(401/403). Fails closed: if user-management is unreachable or errors, the
request is treated as anonymous.

``request.state.user_vendor_id`` (the caller's own vendor, used by
VendorService row-scoping) is hydrated from the context's ``vendor_id``.
"""
from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import extract_bearer_token
from app.services.user_mgmt_client import UserMgmtClient
from app.utilities.logger import get_logger


logger = get_logger(__name__)


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


def _decode_scoped(
    raw: Optional[dict],
) -> Dict[Tuple[str, Optional[str]], Set[str]]:
    """Decode the wire `{"kind:id": [codes], "global": [codes]}` map back into
    the `{(kind, id): set(codes)}` shape the scope-aware gates expect."""
    out: Dict[Tuple[str, Optional[str]], Set[str]] = {}
    for key, codes in (raw or {}).items():
        if ":" in key:
            kind, scope_id = key.split(":", 1)
        else:
            kind, scope_id = key, None
        out[(kind, scope_id)] = set(codes or [])
    return out


def _set_anonymous(request: Request) -> None:
    request.state.user_id = None
    request.state.user_login = None
    request.state.user_email = None
    request.state.token_jti = None
    request.state.user_permissions = set()  # type: Set[str]
    request.state.scoped_permissions = {}
    request.state.user_vendor_id = None
    request.state.is_admin = False


class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that hydrates request.state from the authz context."""

    async def dispatch(self, request: Request, call_next):
        _set_anonymous(request)

        if _is_public_path(request.url.path):
            return await call_next(request)

        authorization = request.headers.get("authorization")
        token = extract_bearer_token(authorization)
        if not token:
            return await call_next(request)

        try:
            ctx = UserMgmtClient().fetch_authz_context(authorization)
        except Exception as exc:  # noqa: BLE001 — never crash on the authz call
            logger.warning("authz context fetch failed: %s", exc)
            ctx = None

        if ctx:
            request.state.user_id = ctx.get("user_id")
            request.state.user_permissions = set(ctx.get("permissions") or [])
            request.state.scoped_permissions = _decode_scoped(ctx.get("scoped"))
            request.state.user_vendor_id = ctx.get("vendor_id")

        return await call_next(request)
