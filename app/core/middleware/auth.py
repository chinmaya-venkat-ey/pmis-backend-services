"""
Authentication middleware for JWT validation.
"""
from datetime import datetime, timezone
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from ..security import decode_access_token
from ..rbac import Role


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to authenticate requests using JWT Bearer tokens.

    Pipeline:
    1. Extract JWT token from Authorization header
    2. Validate and decode the token (signature + expiry)
    3. Check the token's ``jti`` against the revocation blacklist
       (RevokedTokenModel). Revoked tokens are treated as if absent —
       request.state stays anonymous and downstream RBAC will reject
       protected routes with 401.
    4. Attach user information to request.state for downstream handlers
       AND publish ``token_jti`` / ``token_exp`` so the logout endpoint
       can revoke the *current* token without re-decoding it.

    Tokens issued before the jti claim was added (or any other token
    without a ``jti`` claim) are NEVER considered revoked — the blacklist
    lookup short-circuits on missing jti. They expire naturally.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable
    ) -> Response:
        # Initialize request state with anonymous user
        request.state.user_id = None
        request.state.user_login = None
        request.state.user_role = Role.ANONYMOUS
        request.state.is_admin = False
        request.state.token_jti = None
        request.state.token_exp = None

        # Extract Authorization header
        auth_header = request.headers.get("Authorization")

        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

            # Decode and validate token (signature + expiry).
            payload = decode_access_token(token)

            if payload:
                jti = payload.get("jti")
                # Blacklist check. Open a short-lived session; the lookup
                # is one indexed PK probe — microseconds on SQLite, fine
                # to do per-request.
                if jti and self._is_revoked(jti):
                    # Treat revoked tokens exactly like anonymous —
                    # downstream RBAC rejects with 401.
                    response = await call_next(request)
                    return response

                # Attach user information to request state.
                request.state.user_id = payload.get("user_id")
                request.state.user_login = payload.get("sub")
                request.state.user_role = Role(payload.get("role", Role.ANONYMOUS.value))
                request.state.is_admin = payload.get("is_admin", False)
                request.state.token_jti = jti
                # exp is a Unix timestamp; convert to UTC datetime so the
                # logout service can persist it as expires_at without
                # re-decoding the token.
                exp_ts = payload.get("exp")
                if exp_ts is not None:
                    try:
                        request.state.token_exp = datetime.fromtimestamp(
                            int(exp_ts), tz=timezone.utc
                        )
                    except (TypeError, ValueError):
                        request.state.token_exp = None

        # Continue processing
        response = await call_next(request)
        return response

    @staticmethod
    def _is_revoked(jti: str) -> bool:
        """Lookup against the revocation blacklist. Imports are local so
        this module stays importable even if DB models aren't loaded yet
        (e.g. during early test bootstrap)."""
        from ...infrastructure.db.session import SessionLocal
        from ...infrastructure.db.repositories.revoked_token_repository import (
            RevokedTokenRepository,
        )
        db = SessionLocal()
        try:
            return RevokedTokenRepository(db).is_revoked(jti)
        finally:
            db.close()
