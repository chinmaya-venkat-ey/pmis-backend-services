"""OTP code generation + hashing.

OTP codes are 6 digits by default (settings.otp_code_length). Stored as
HMAC-SHA256 over the code with `OTP_HASH_PEPPER` as the key — so a DB
leak doesn't yield clear-text codes, AND a missing pepper makes existing
hashes uncomparable (additional safety on misconfig).

Ported from C:\\Programming\\PMIS\\PMIS-user-management\\app\\shared\\otp.py.
"""
from __future__ import annotations

import hmac
import secrets
from hashlib import sha256
from uuid import uuid4

from app.config import settings


def generate_otp_code(length: int | None = None) -> str:
    """Generate a numeric OTP of the configured length (default 6)."""
    n = length if length is not None else settings.otp_code_length
    # Uniform random across [0, 10**n) zero-padded.
    upper = 10 ** n
    return f"{secrets.randbelow(upper):0{n}d}"


def hash_otp_code(code: str) -> str:
    """HMAC-SHA256 the OTP code with the configured pepper."""
    pepper = (settings.otp_hash_pepper or "").encode("utf-8")
    return hmac.new(pepper, code.encode("utf-8"), sha256).hexdigest()


def verify_otp_code(plain_code: str, hashed_code: str) -> bool:
    """Constant-time compare."""
    return hmac.compare_digest(hash_otp_code(plain_code), hashed_code)


def generate_ephemeral_token() -> str:
    """Generate a one-shot opaque token returned to the FE when 2FA is required.

    The FE includes it in the subsequent send-otp / verify-otp calls so we
    can look up the OTP row without exposing the user_id in the URL.
    """
    return uuid4().hex


def hash_ephemeral_token(token: str) -> str:
    """HMAC-SHA256 the ephemeral token with the configured pepper."""
    pepper = (settings.otp_hash_pepper or "").encode("utf-8")
    return hmac.new(pepper, token.encode("utf-8"), sha256).hexdigest()
