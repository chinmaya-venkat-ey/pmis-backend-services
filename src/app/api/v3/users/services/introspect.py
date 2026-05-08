"""
Token introspection service — RFC 7662 style.

Pure read-only metadata lookup. NEVER rotates tokens; rotation lives in
``services.refresh.refresh_tokens`` behind the dedicated
``POST /api/v3/users/refresh`` endpoint.

Returns a flat dict with the standard claim names:
    active, exp, iat, jti, sub, username, user_id, email, role, isAdmin,
    tokenType ('access' | 'refresh')

For an expired or unparseable token: ``{"active": false}`` (no payload
fields). The caller treats this as a 200 with the negative answer rather
than an error — matches RFC 7662's "active=false on inactive tokens".

Both ``access_token`` and ``refresh_token`` are accepted in the request
body (either or both). When both are supplied, two introspection results
are returned under ``access`` and ``refresh`` keys. When only one is
supplied, the response is a single inline result.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from .....core.security import verify_access_token, verify_refresh_token
from .....infrastructure.db.repositories.revoked_token_repository import (
    RevokedTokenRepository,
)
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult


def _claims_to_response(
    payload: Dict[str, Any], *, token_type: str,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Project a decoded JWT payload into the public introspect response shape.

    Doc 21 part B: ``role`` and ``isAdmin`` are resolved from the DB at
    introspect time (the JWT no longer carries those claims). Tokens
    issued before the rework still carry ``role``/``is_admin`` claims;
    those are honored as a fallback if a DB lookup isn't possible.
    """
    exp = payload.get("exp")
    iat = payload.get("iat")
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)
    if db is not None and user_id is not None:
        # Local import to avoid module-load cycles.
        from .....infrastructure.db.repositories.rbac_repository import (
            RbacRepository,
        )
        is_admin = RbacRepository(db).user_has_admin_role(user_id)
    return {
        "active": True,
        "tokenType": token_type,
        "exp": exp,
        "iat": iat,
        "expiresAt": (
            datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
            if isinstance(exp, (int, float)) else None
        ),
        "issuedAt": (
            datetime.fromtimestamp(iat, tz=timezone.utc).isoformat()
            if isinstance(iat, (int, float)) else None
        ),
        "jti": payload.get("jti"),
        "sub": payload.get("sub"),
        "username": payload.get("sub"),
        "userId": user_id,
        "email": payload.get("email"),
        # ``role`` is no longer a single value in the new model. Kept here
        # as None for back-compat with old FE consumers; use the
        # /users/me/permissions endpoint for the authoritative answer.
        "role": payload.get("role"),
        "isAdmin": bool(is_admin),
    }


def _introspect_access(db: Session, token: str) -> Dict[str, Any]:
    """Introspect one access token. Always returns a dict (never raises)."""
    is_valid, _is_expired, payload = verify_access_token(token)
    if not is_valid or not payload:
        return {"active": False, "tokenType": "access"}

    # Active = signature valid AND not expired AND jti not in the
    # revoked-token blacklist (logout adds it). Only when all three hold
    # does the FE consider the token usable.
    jti = payload.get("jti")
    if jti and RevokedTokenRepository(db).is_revoked(jti):
        return {"active": False, "tokenType": "access"}

    return _claims_to_response(payload, token_type="access", db=db)


def _introspect_refresh(db: Session, token: str) -> Dict[str, Any]:
    """Introspect one refresh token. Always returns a dict (never raises).

    A refresh token is "active" when:
      - signature is valid AND not expired
      - its jti matches EITHER the user row's stored ``refresh_token_jti``
        (the latest issued) OR the ``previous_refresh_token_jti`` while
        the grace window (``previous_refresh_token_jti_valid_until``) is
        still open. Outside the grace window, only the current jti
        counts as active.
      - the user row's stored ``refresh_token_expires_at`` is in the future
        (only enforced when the incoming token resolves to the current slot;
        the previous slot is bounded by the grace window itself).
    """
    payload = verify_refresh_token(token)
    if not payload:
        return {"active": False, "tokenType": "refresh"}

    user_id = payload.get("user_id")
    jti = payload.get("jti")
    if not user_id or not jti:
        return {"active": False, "tokenType": "refresh"}

    repo = UserRepository(db)
    (
        current_jti,
        current_expires,
        previous_jti,
        previous_valid_until,
    ) = repo.get_refresh_metadata_with_grace(user_id)

    now = datetime.now(timezone.utc)
    matches_current = bool(current_jti) and current_jti == jti
    matches_previous_in_grace = (
        bool(previous_jti)
        and previous_jti == jti
        and previous_valid_until is not None
        and _as_utc(previous_valid_until) > now
    )

    if not (matches_current or matches_previous_in_grace):
        return {"active": False, "tokenType": "refresh"}

    if matches_current and current_expires is not None:
        if _as_utc(current_expires) < now:
            return {"active": False, "tokenType": "refresh"}

    return _claims_to_response(payload, token_type="refresh", db=db)


def _as_utc(dt: datetime) -> datetime:
    """Coerce a naive datetime to aware UTC. SQLite drops tzinfo on
    round-trip; Postgres preserves it."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def introspect_tokens(
    db: Session,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
) -> ServiceResult[Dict[str, Any]]:
    """Introspect one or both tokens.

    Returns:
      - Single token supplied → flat result dict ({"active": ..., ...}).
      - Both supplied → ``{"access": {...}, "refresh": {...}}``.
      - Neither → 422 validation_error.

    Never rotates. Rotation is the responsibility of ``refresh_tokens``.
    """
    if not access_token and not refresh_token:
        return ServiceResult.fail(
            error="No token provided. Supply 'access_token' or 'refresh_token'.",
            error_type="validation_error",
        )

    if access_token and refresh_token:
        return ServiceResult.ok({
            "access": _introspect_access(db, access_token),
            "refresh": _introspect_refresh(db, refresh_token),
        })

    if access_token:
        return ServiceResult.ok(_introspect_access(db, access_token))

    return ServiceResult.ok(_introspect_refresh(db, refresh_token))
