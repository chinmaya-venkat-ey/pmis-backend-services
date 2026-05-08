"""
Authentication middleware for JWT validation.

Doc 21 part B: after token decode, the middleware looks up the user's
effective permission set (role-derived ∪ direct grants) and stores it
on ``request.state.user_permissions``. The decorator
``require_permission(code)`` reads from that Set on each call. ``is_admin``
is derived from membership in the seeded ``admin`` role — the legacy
``users.admin`` boolean column is gone.

The lookup is one indexed JOIN per authenticated request. For anonymous
or revoked-token requests the lookup is skipped and ``user_permissions``
stays empty, which causes every ``require_permission`` to reject with 401.

Doc 27 hotfix — pre-doc-26 token guard: ``users.id`` was flipped from
auto-incrementing integer to UUID String(36) in doc 26. JWTs minted
before that change carry an integer ``user_id`` claim (e.g. ``1``)
which can no longer be used to query the now-string ``user_roles.user_id``
column without Postgres throwing ``operator does not exist:
character varying = integer``. The guard below rejects any token whose
``user_id`` claim isn't a UUID-shaped string — the request is treated
as anonymous and downstream ``require_permission`` returns 401, which
the FE handles as "session expired, re-login." Cleaner than a 500
trace in the logs.
"""
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from ..security import decode_access_token


def _is_valid_user_id_claim(value: Any) -> bool:
    """True iff ``value`` is a string that parses as a valid UUID.

    Doc 27 hotfix: rejects pre-doc-26 integer claims (``1``, ``2``, …)
    AND any malformed claim shape — protects every downstream call site
    that assumes ``request.state.user_id`` is a UUID string.
    """
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
        call_next: Callable
    ) -> Response:
        request.state.user_id = None
        request.state.user_login = None
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
                    response = await call_next(request)
                    return response

                user_id = payload.get("user_id")
                # Doc 27 hotfix — defensive guard. Pre-doc-26 tokens
                # carry an integer user_id; passing that to any post-
                # doc-26 query against the UUID-typed users.id column
                # blows up with a 500 (psycopg2 ProgrammingError on
                # Postgres). Reject the token cleanly here so the
                # request is anonymous → require_permission returns 401
                # → FE re-login flow kicks in. Same outcome as any
                # other "expired token" case.
                if not _is_valid_user_id_claim(user_id):
                    response = await call_next(request)
                    return response

                request.state.user_id = user_id
                request.state.user_login = payload.get("sub")
                request.state.token_jti = jti
                exp_ts = payload.get("exp")
                if exp_ts is not None:
                    try:
                        request.state.token_exp = datetime.fromtimestamp(
                            int(exp_ts), tz=timezone.utc
                        )
                    except (TypeError, ValueError):
                        request.state.token_exp = None

                # Hydrate effective permission set + admin flag from DB.
                perms, is_admin = self._load_user_permissions(user_id)
                request.state.user_permissions = perms
                request.state.is_admin = is_admin

        response = await call_next(request)
        return response

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
    def _load_user_permissions(user_id: str):
        """Returns (permissions: Set[str], is_admin: bool)."""
        from ...infrastructure.db.session import SessionLocal
        from ...infrastructure.db.repositories.rbac_repository import (
            RbacRepository,
        )
        db = SessionLocal()
        try:
            repo = RbacRepository(db)
            perms = repo.effective_permissions_for_user(user_id)
            is_admin = repo.user_has_admin_role(user_id)
            return perms, is_admin
        finally:
            db.close()
