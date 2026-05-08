"""OTP + password-reset token primitives (doc 33 change 3).

Hashing
-------
Codes (numeric OTP and URL-safe reset tokens) are stored as
``HMAC-SHA256(server_pepper, code)`` so the DB never holds plaintext.
The pepper is ``settings.OTP_HASH_PEPPER`` if set, falling back to
``settings.SECRET_KEY`` so deployments that don't set a separate pepper
still get a non-empty key.

Constant-time comparison
------------------------
Verification uses ``hmac.compare_digest`` to dodge the timing-attack
class.

These helpers are pure utility functions — the service layer wires
them into the OTP / reset flows.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Tuple

from ..core.config import settings


# Reset-token byte length for the email URL form. 32 random bytes →
# 43 chars URL-safe base64.
RESET_TOKEN_BYTES = 32


def _pepper() -> bytes:
    """Server-side pepper. Falls back to SECRET_KEY when not configured."""
    pepper = settings.OTP_HASH_PEPPER or settings.SECRET_KEY
    return pepper.encode("utf-8")


def hash_secret(value: str) -> str:
    """HMAC-SHA256(pepper, value) → hex string."""
    return hmac.new(_pepper(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_secret(value: str, expected_hash: str) -> bool:
    """Constant-time hash comparison."""
    return hmac.compare_digest(hash_secret(value), expected_hash)


def generate_numeric_code(length: int) -> str:
    """Cryptographically random numeric code of the given length.

    Uses ``secrets.randbelow`` so each digit is uniformly distributed
    (vs. ``secrets.choice("0123456789")`` which works but reads less
    obviously correct).
    """
    if length <= 0:
        raise ValueError("OTP code length must be > 0")
    upper = 10 ** length
    return f"{secrets.randbelow(upper):0{length}d}"


def generate_url_token() -> str:
    """URL-safe random token for email-based password resets."""
    return secrets.token_urlsafe(RESET_TOKEN_BYTES)


def generate_ephemeral_token() -> str:
    """Opaque session token returned at /login stage 1.

    Identifies the in-progress 2FA session — the client passes it back
    to /login/send-otp and /login/verify-otp. Stored hashed in
    ``otp_codes.ephemeral_token_hash`` so a DB read can't replay an
    in-flight session.
    """
    return secrets.token_urlsafe(32)
