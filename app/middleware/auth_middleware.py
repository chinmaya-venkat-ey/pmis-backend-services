"""Auth middleware for pmis-file-store — pure Policy Enforcement Point.

Forwards the caller's ``Authorization`` header to user-management's
``GET /api/v3/authz/context`` and hydrates ``request.state`` from the decided
context. This service no longer resolves permissions from ``users.*`` itself —
the old cross-schema ``RbacReadRepository`` (and its phantom
``users.users.admin`` column) are gone.

Fails closed: if user-management is unreachable or errors, the request is
treated as anonymous and the route's ``require_*`` gate returns 401/403.
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
    the `{(kind, id): set(codes)}` shape the scope-aware gates expect. A key
    with no `:` (i.e. `global`) decodes to `(kind, None)`."""
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
    request.state.is_admin = False
    request.state.vendor_id = None


class AuthMiddleware(BaseHTTPMiddleware):
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
        except Exception as exc:  # noqa: BLE001
            # user-management unreachable / errored — fail closed (anonymous).
            logger.warning("authz context fetch failed: %s", exc)
            ctx = None

        if ctx:
            request.state.user_id = ctx.get("user_id")
            request.state.user_permissions = set(ctx.get("permissions") or [])
            request.state.scoped_permissions = _decode_scoped(ctx.get("scoped"))
            request.state.vendor_id = ctx.get("vendor_id")

        return await call_next(request)
