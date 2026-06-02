"""Password-reset token generation + hashing.

The token returned to the user (via email link) is a high-entropy URL-safe
string. The DB stores only an HMAC-SHA256 hash (so leak of DB doesn't expose
live reset tokens). Single-use is enforced at the service layer by setting
`consumed_at` on first verify.

Ported from C:\\Programming\\PMIS\\PMIS-user-management\\app\\services\\password_reset.py
helpers.
"""
from __future__ import annotations

import hmac
import secrets
from hashlib import sha256

from app.config import settings


def generate_reset_token() -> str:
    """Generate a 32-byte URL-safe token (~43 chars base64url, ~256 bits)."""
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    """HMAC-SHA256 the reset token with OTP_HASH_PEPPER (reused as the key)."""
    pepper = (settings.otp_hash_pepper or "").encode("utf-8")
    return hmac.new(pepper, token.encode("utf-8"), sha256).hexdigest()


def verify_reset_token(plain_token: str, hashed_token: str) -> bool:
    """Constant-time compare."""
    return hmac.compare_digest(hash_reset_token(plain_token), hashed_token)
