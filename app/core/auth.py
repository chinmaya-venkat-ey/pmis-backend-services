"""JWT decode helpers (doc 38).

This service verifies tokens minted by user-service using the shared
SECRET_KEY. Same algorithm (HS256), same claim shape:
``{sub, user_id, email, jti, iat, exp}``.

Pre-doc-38 this service had no auth — it was a stateless dispatcher
called from inside the trust boundary. Doc 38 introduces auth on
``/api/v3/master/*`` only; the legacy dispatch endpoints (``/api/v1/
notifications/...``) stay unauthenticated for back-compat.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import jwt

from ..config import settings


logger = logging.getLogger(__name__)


# Settings-style attribute lookup with fallback to the legacy lower-case
# names this repo originally used.
def _setting(*names: str, default: Any = None) -> Any:
    for n in names:
        if hasattr(settings, n):
            v = getattr(settings, n)
            if v is not None and v != "":
                return v
    return default


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a JWT minted by user-service.

    Returns the claims dict on success, ``None`` on any failure
    (expired / invalid signature / malformed). Doesn't raise — auth
    middleware translates the missing-claims case to 401.
    """
    secret = _setting("secret_key", "SECRET_KEY", default="")
    algorithm = _setting("algorithm", "ALGORITHM", default="HS256")
    if not secret:
        logger.warning("decode_access_token called but SECRET_KEY is unset")
        return None
    try:
        return jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:  # noqa: BLE001 — defensive
        logger.exception("Unexpected JWT decode error")
        return None
