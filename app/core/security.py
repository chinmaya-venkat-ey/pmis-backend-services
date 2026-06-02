"""JWT + argon2 + token-id helpers — CANONICAL declaration site.

Owns:
  - argon2id password hashing + verification
  - JWT access-token creation + decode + expired-token introspection
  - JWT refresh-token creation + decode (with grace window in user-svc)

Other services duplicate only the DECODE portion (no token issuance, no
password hashing). Keep the decode signature byte-identical or JWT
verification breaks across services.

Ported from C:\\Programming\\PMIS\\PMIS-user-management\\app\\core\\security.py:1-179
with these adjustments:
  - Uses lower-case settings attributes (matches our config.py convention).
  - Adds `extract_bearer_token` helper (was duplicated inline in middleware).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from jose import ExpiredSignatureError, JWTError, jwt

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# argon2-cffi hasher — argon2id by default
_ph = PasswordHasher()


# ---------------------------------------------------------------------------
# Password hashing (argon2id)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password using argon2id."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against an argon2id hash. Never raises."""
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ---------------------------------------------------------------------------
# JWT — access token
# ---------------------------------------------------------------------------

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT access token with a fresh jti.

    Caller passes claims (`sub`, `user_id`, `email`, ...); this helper stamps
    `iat`, `exp`, `jti` and encodes with the shared SECRET_KEY.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.access_token_expire_minutes
        )
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": uuid4().hex,
    })
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode + verify a JWT access token. Returns claims or None.

    Never raises. Same signature must hold across services.
    """
    if not token:
        return None
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except ExpiredSignatureError:
        logger.debug("JWT decode: expired token")
        return None
    except JWTError as exc:
        logger.debug("JWT decode failed: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("JWT decode raised unexpectedly: %s", exc)
        return None


def verify_access_token(
    token: str,
) -> Tuple[bool, bool, Optional[Dict[str, Any]]]:
    """Decode and distinguish valid / expired / invalid.

    Returns (is_valid, is_expired, payload_or_none). Used by the /introspect
    endpoint to report token state to the caller.
    """
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return True, False, payload
    except ExpiredSignatureError:
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.algorithm],
                options={"verify_exp": False},
            )
            return False, True, payload
        except JWTError:
            return False, True, None
    except JWTError:
        return False, False, None


# ---------------------------------------------------------------------------
# JWT — refresh token
# ---------------------------------------------------------------------------

def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> Tuple[str, str, datetime]:
    """Create a JWT refresh token. Returns (token, jti, expires_at)."""
    to_encode = data.copy()
    jti = uuid4().hex
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.refresh_token_expire_days
        )
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": jti,
    })
    encoded = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded, jti, expire


def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode + verify a refresh token. Returns claims or None."""
    if not token:
        return None
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_bearer_token(authorization_header: Optional[str]) -> Optional[str]:
    """Pull the raw token out of an `Authorization: Bearer <token>` header."""
    if not authorization_header:
        return None
    parts = authorization_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
