"""Authentication middleware — JWT validation for pmis-project-service.

Tokens are minted by user-service (HS256, shared SECRET_KEY). The middleware
decodes the JWT, optionally checks the shared `revoked_tokens` blacklist,
and hydrates `request.state` with:

- `user_id`     — UUID string (post-doc-26)
- `user_login`  — JWT `sub` claim
- `user_role`   — role string from the JWT `role` claim
- `is_admin`    — bool from the JWT `is_admin` claim
- `user_permissions` — Set[str] derived from `user_role` via the static
  `ROLE_PERMISSIONS` map in `app/core/rbac.py`. Admin users get the full
  permission set.

This is intentionally simpler than the monolith's DB-driven RBAC. user-service
does not yet mint a `permissions: List[str]` claim, and project-service does
not host the doc-21B normalized permission tables. Mapping role → permission
set in code keeps the auth path zero-DB.

Doc 27 hotfix: pre-doc-26 tokens carry an integer ``user_id`` claim; reject
them as anonymous so the FE re-login flow kicks in instead of a 500.
"""
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..security import decode_access_token


def _is_valid_user_id_claim(value: Any) -> bool:
    """True iff ``value`` is a string that parses as a UUID."""
    if not isinstance(value, str) or not value:
        return False
    try:
        UUID(value)
        return True
    except (TypeError, ValueError):
        return False


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        request.state.user_id = None
        request.state.user_login = None
        request.state.user_role = None
        request.state.user_permissions = set()
        request.state.is_admin = False
        request.state.token_jti = None
        request.state.token_exp = None

        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            payload = decode_access_token(token)
            if payload:
                jti = payload.get("jti")
                if jti and self._is_revoked(jti):
                    return await call_next(request)

                user_id = payload.get("user_id")
                if not _is_valid_user_id_claim(user_id):
                    return await call_next(request)

                request.state.user_id = user_id
                request.state.user_login = payload.get("sub")
                request.state.token_jti = jti
                exp_ts = payload.get("exp")
                if exp_ts is not None:
                    try:
                        request.state.token_exp = datetime.fromtimestamp(
                            int(exp_ts), tz=timezone.utc,
                        )
                    except (TypeError, ValueError):
                        request.state.token_exp = None

                # Hydrate permissions from JWT role claim via static map.
                # Tokens are minted by user-service (post doc 37 part 2),
                # which always includes `role` + `is_admin` in claims.
                # Monolith forwards user/auth requests to user-service via
                # the proxy when USER_SERVICE_PROXY_ENABLED=true.
                role_value = payload.get("role")
                is_admin = bool(payload.get("is_admin"))
                request.state.user_role = role_value
                request.state.is_admin = is_admin
                request.state.user_permissions = self._role_permissions(
                    role_value, is_admin,
                )

        return await call_next(request)

    @staticmethod
    def _is_revoked(jti: str) -> bool:
        from ...infrastructure.db.session import SessionLocal
        from ...infrastructure.db.repositories.revoked_token_repository import (
            RevokedTokenRepository,
        )
        db = SessionLocal()
        try:
            return RevokedTokenRepository(db).is_revoked(jti)
        finally:
            db.close()

    @staticmethod
    def _role_permissions(role_value: Any, is_admin: bool) -> set:
        """Look up the static permission set for the role.

        Admins always get the full registry — convenient for the
        ``ALL_PERMISSIONS`` set defined in core/rbac.py.
        """
        from ..rbac import Permission, ROLE_PERMISSIONS, Role

        if is_admin:
            return {p.value for p in Permission}

        if not role_value:
            return set()

        try:
            role = Role(role_value)
        except ValueError:
            return set()

        return {p.value for p in ROLE_PERMISSIONS.get(role, set())}
