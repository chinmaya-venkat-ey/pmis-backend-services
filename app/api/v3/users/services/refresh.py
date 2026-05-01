"""Refresh-token rotation service.

Backs ``POST /api/v3/users/refresh``. Takes a refresh token, validates
it against the user row's stored jti + expiry, and on success issues a
fresh access + refresh pair.

The user row carries TWO valid jtis at any moment:

* ``refresh_token_jti``                              — the latest one issued.
* ``previous_refresh_token_jti`` (with valid_until)  — the one rotated out
  just now; remains acceptable for ``REFRESH_TOKEN_GRACE_SECONDS``.

Both are accepted by this service. Each successful refresh shifts the
current jti into the previous slot and writes the freshly-minted jti to
the live slot. The grace window absorbs concurrent refresh races
(timer + 401-interceptor firing in parallel), multi-tab/multi-device
login interleaves, and stale-token retries from middleware.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from .....core.security import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
)
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult


def _as_utc(dt: datetime) -> datetime:
    """Coerce a possibly-naive datetime to a timezone-aware UTC datetime.

    SQLite drops tzinfo on round-trip; Postgres preserves it. We treat
    a naive value as already-UTC so the comparison against
    ``datetime.now(tz=UTC)`` doesn't raise a TypeError.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _exp_metadata(token: str) -> Dict[str, Any]:
    """Decode a freshly-minted token (no signature check needed — we just
    minted it) to surface its expiry / issued-at timestamps to the caller."""
    from jose import jwt
    from .....core.config import settings
    payload = jwt.decode(
        token, settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        options={"verify_exp": False},
    )
    exp = payload.get("exp")
    iat = payload.get("iat")
    return {
        "expiresAt": (
            datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
            if isinstance(exp, (int, float)) else None
        ),
        "issuedAt": (
            datetime.fromtimestamp(iat, tz=timezone.utc).isoformat()
            if isinstance(iat, (int, float)) else None
        ),
        "exp": exp,
        "iat": iat,
    }


def refresh_tokens(
    db: Session,
    refresh_token: Optional[str] = None,
) -> ServiceResult[Dict[str, Any]]:
    """Validate a refresh token and rotate to a new pair.

    Returns:
        On success: dict with the new access + refresh tokens, the rotated
        user, and expiry metadata for both tokens.
        On failure: ServiceResult.fail with errorIdentifier=
        ``authentication_error`` and a 401 from the controller.
    """
    if not refresh_token:
        return ServiceResult.fail(
            error="refresh_token is required.",
            error_type="validation_error",
        )

    payload = verify_refresh_token(refresh_token)
    if not payload:
        return ServiceResult.fail(
            error="Invalid refresh token.",
            error_type="authentication_error",
        )

    user_id = payload.get("user_id")
    token_jti = payload.get("jti")
    if not user_id or not token_jti:
        return ServiceResult.fail(
            error="Invalid refresh token payload.",
            error_type="authentication_error",
        )

    repo = UserRepository(db)
    (
        current_jti,
        current_expires,
        previous_jti,
        previous_valid_until,
    ) = repo.get_refresh_metadata_with_grace(user_id)

    now = datetime.now(timezone.utc)

    # Decide which jti slot the incoming token resolves to. Accept the
    # previous slot only while inside the grace window; outside, treat
    # it as already rotated out.
    matches_current = bool(current_jti) and current_jti == token_jti
    matches_previous_in_grace = (
        bool(previous_jti)
        and previous_jti == token_jti
        and previous_valid_until is not None
        and _as_utc(previous_valid_until) > now
    )

    if not (matches_current or matches_previous_in_grace):
        return ServiceResult.fail(
            error="Refresh token invalid or already rotated.",
            error_type="authentication_error",
        )

    # Hard-expiry check on the live token's TTL. Only enforced on the
    # CURRENT slot — the previous slot lives only as long as the grace
    # window so its underlying TTL is moot.
    if matches_current and current_expires is not None:
        if _as_utc(current_expires) < now:
            return ServiceResult.fail(
                error="Refresh token expired.",
                error_type="authentication_error",
            )

    # Mint the new pair with the same identity claims as the old refresh.
    token_data = {
        "sub": payload.get("sub"),
        "user_id": user_id,
        "email": payload.get("email"),
        "role": payload.get("role"),
        "is_admin": payload.get("is_admin", False),
    }
    new_access = create_access_token(token_data)
    new_refresh, new_jti, new_expires = create_refresh_token(token_data)

    # Unconditional rotation. The repository captures the outgoing
    # ``current_jti`` into the previous slot with the configured grace
    # TTL, then writes the new jti into the current slot — single
    # transaction, so callers never see torn state. There's no
    # expected-old-jti check anymore: the validation above already
    # ensured the caller is authorized, so concurrent refreshes BOTH
    # succeed (each producing its own fresh pair).
    from .....core.config import settings as _settings
    repo.rotate_refresh_token(
        user_id, new_jti, new_expires,
        grace_seconds=_settings.REFRESH_TOKEN_GRACE_SECONDS,
    )

    user = repo.get_by_id(user_id)
    if not user:
        return ServiceResult.fail(
            error="User not found.",
            error_type="not_found",
        )

    access_meta = _exp_metadata(new_access)
    refresh_meta = _exp_metadata(new_refresh)

    return ServiceResult.ok({
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "accessTokenExpiresAt": access_meta["expiresAt"],
        "accessTokenIssuedAt": access_meta["issuedAt"],
        "refreshTokenExpiresAt": refresh_meta["expiresAt"],
        "refreshTokenIssuedAt": refresh_meta["issuedAt"],
        "expiresInSeconds": (
            int(access_meta["exp"] - access_meta["iat"])
            if access_meta["exp"] and access_meta["iat"] else None
        ),
        "user": user,
    })
