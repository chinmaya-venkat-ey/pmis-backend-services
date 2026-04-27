"""JWT authentication middleware — ported from the monolith.

Verifies the Bearer token (via the shared JWTProvider through
``core.security.decode_access_token``), checks the jti against the
blacklist, and publishes user info + jti/exp on ``request.state`` for
downstream handlers (notably the logout service).
"""
from datetime import datetime, timezone
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..rbac import Role
from ..security import decode_access_token


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Anonymous defaults
        request.state.user_id = None
        request.state.user_login = None
        request.state.user_role = Role.ANONYMOUS
        request.state.is_admin = False
        request.state.token_jti = None
        request.state.token_exp = None

        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            payload = decode_access_token(token)
            if payload:
                jti = payload.get("jti")
                if jti and self._is_revoked(jti):
                    # Revoked → treat as anonymous; downstream RBAC rejects.
                    return await call_next(request)

                request.state.user_id = payload.get("user_id")
                request.state.user_login = payload.get("sub")
                request.state.user_role = Role(
                    payload.get("role", Role.ANONYMOUS.value)
                )
                request.state.is_admin = payload.get("is_admin", False)
                request.state.token_jti = jti

                exp_ts = payload.get("exp")
                if exp_ts is not None:
                    try:
                        request.state.token_exp = datetime.fromtimestamp(
                            int(exp_ts), tz=timezone.utc,
                        )
                    except (TypeError, ValueError):
                        request.state.token_exp = None

        return await call_next(request)

    @staticmethod
    def _is_revoked(jti: str) -> bool:
        """Blacklist check. Local import so this module stays importable
        before DB models load (e.g. early test bootstrap)."""
        from ...infrastructure.db.repositories.revoked_token_repository import (
            RevokedTokenRepository,
        )
        from ...infrastructure.db.session import SessionLocal

        db = SessionLocal()
        try:
            return RevokedTokenRepository(db).is_revoked(jti)
        finally:
            db.close()
