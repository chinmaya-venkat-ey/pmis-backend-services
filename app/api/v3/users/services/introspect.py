"""Token introspection + refresh rotation — ported from the monolith.

- Valid access token → active:true + user info.
- Expired access token + valid refresh → rotate and issue new pair.
- Invalid / reused / expired refresh → 401.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .....core.security import (
    create_access_token,
    create_refresh_token,
    verify_access_token,
    verify_refresh_token,
)
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult


def introspect_tokens(
    db: Session,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
) -> ServiceResult[dict]:
    if not access_token and not refresh_token:
        return ServiceResult.fail(
            error="No token provided", error_type="validation_error",
        )

    repo = UserRepository(db)

    # Fast path: valid access token.
    if access_token:
        is_valid, is_expired, payload = verify_access_token(access_token)
        if is_valid:
            user = repo.get_by_id(payload.get("user_id"))
            if not user:
                return ServiceResult.fail(
                    error="User not found", error_type="not_found",
                )
            return ServiceResult.ok({"active": True, "user": user})

        if is_expired and not refresh_token:
            return ServiceResult.fail(
                error="Access token expired; refresh token required",
                error_type="authentication_error",
            )

    # Refresh path.
    if refresh_token:
        refresh_payload = verify_refresh_token(refresh_token)
        if not refresh_payload:
            return ServiceResult.fail(
                error="Invalid refresh token", error_type="authentication_error",
            )

        user_id = refresh_payload.get("user_id")
        token_jti = refresh_payload.get("jti")
        if not user_id or not token_jti:
            return ServiceResult.fail(
                error="Invalid refresh token payload",
                error_type="authentication_error",
            )

        stored_jti, stored_expires = repo.get_refresh_metadata(user_id)
        if not stored_jti or stored_jti != token_jti:
            return ServiceResult.fail(
                error="Refresh token invalid or reused",
                error_type="authentication_error",
            )
        if stored_expires is not None:
            # SQLite returns naive datetimes (tz stripped on retrieval);
            # Postgres preserves tz-aware values. Normalize: if stored
            # value is naive, treat it as UTC (which is what we write).
            stored_aware = (
                stored_expires
                if stored_expires.tzinfo is not None
                else stored_expires.replace(tzinfo=timezone.utc)
            )
            if stored_aware < datetime.now(timezone.utc):
                return ServiceResult.fail(
                    error="Refresh token expired",
                    error_type="authentication_error",
                )

        token_data = {
            "sub": refresh_payload.get("sub"),
            "user_id": user_id,
            "email": refresh_payload.get("email"),
            "role": refresh_payload.get("role"),
            "is_admin": refresh_payload.get("is_admin", False),
        }
        new_access = create_access_token(token_data)
        new_refresh, new_jti, new_expires = create_refresh_token(token_data)

        # Atomic rotation — blocks silent overwrite of a rotated token.
        updated = repo.update_refresh_token_metadata(
            user_id, new_jti, new_expires, expected_old_jti=token_jti,
        )
        if not updated:
            return ServiceResult.fail(
                error="Refresh token invalid or reused",
                error_type="authentication_error",
            )

        user = repo.get_by_id(user_id)
        if not user:
            return ServiceResult.fail(
                error="User not found", error_type="not_found",
            )

        return ServiceResult.ok({
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "user": user,
        })

    return ServiceResult.fail(
        error="Invalid or expired tokens", error_type="authentication_error",
    )
