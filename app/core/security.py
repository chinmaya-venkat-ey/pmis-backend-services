"""Security utilities — JWT signing/verification + argon2id password hashing.

Self-contained for this service. No external shared package — the entire
auth surface (this module + ``app/core/middleware/auth.py`` +
``app/core/middleware/rbac.py`` + ``app/core/rbac.py``) lives inside
pmis-user-service.

Cross-service token verification (monolith verifying tokens minted here)
works because both services use HS256 and the same ``SECRET_KEY`` from
their environment. They do NOT need to share Python code — the JWT spec
itself is the contract.

Public API used by services / controllers / middleware / tests:

    hash_password(plain) -> str
    verify_password(plain, hashed) -> bool
    create_access_token(data, expires_delta=None) -> str
    decode_access_token(token) -> dict | None
    verify_access_token(token) -> (is_valid, is_expired, payload | None)
    create_refresh_token(data, expires_delta=None) -> (token, jti, expires_at)
    verify_refresh_token(token) -> dict | None
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)
from jose import ExpiredSignatureError, JWTError, jwt

from .config import settings


# ---- Startup guardrail --------------------------------------------------
# Refuse obviously-weak signing keys at module load. Forging tokens is
# trivial against a short key, so failing loud is better than silently
# accepting one.
if not settings.SECRET_KEY or len(settings.SECRET_KEY) < 16:
    raise ValueError(
        "SECRET_KEY must be a non-empty string of at least 16 characters. "
        "Set it in .env or via environment variable."
    )


# ---- Password hashing (argon2id) ----------------------------------------

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plain password using argon2id."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against an argon2 hash.

    Returns False on any verification or hash-format error rather than
    raising, so callers can use the result as a simple bool.
    """
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ---- JWT — access tokens -----------------------------------------------


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Mint a short-lived access token.

    Each token gets a unique ``jti`` (uuid4 hex) so it can be revoked via
    the access-token blacklist (``RevokedTokenRepository``). The auth
    middleware checks every authenticated request's jti against the
    blacklist before letting the request through.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)

    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": now,
        "jti": uuid4().hex,
    })

    return jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a JWT access token. Returns payload or None."""
    try:
        return jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
        )
    except JWTError:
        return None


def verify_access_token(
    token: str,
) -> Tuple[bool, bool, Optional[Dict[str, Any]]]:
    """Returns ``(is_valid, is_expired, payload_or_none)``.

    Expired-but-otherwise-valid tokens are still parsed so callers can
    extract the payload (useful for refresh flows).
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
        )
        return True, False, payload
    except ExpiredSignatureError:
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": False},
            )
            return False, True, payload
        except JWTError:
            return False, True, None
    except JWTError:
        return False, False, None


# ---- JWT — refresh tokens ----------------------------------------------


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> Tuple[str, str, datetime]:
    """Mint a long-lived refresh token.

    Returns ``(token, jti, expires_at)`` so the caller can persist the
    jti + expiry on the user row for single-active-refresh-token
    enforcement.
    """
    to_encode = data.copy()
    jti = uuid4().hex
    now = datetime.now(timezone.utc)

    if expires_delta:
        expires_at = now + expires_delta
    else:
        expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({
        "exp": expires_at,
        "iat": now,
        "jti": jti,
    })

    encoded = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )
    return encoded, jti, expires_at


def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a refresh token. None on any failure."""
    try:
        return jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
        )
    except JWTError:
        return None
