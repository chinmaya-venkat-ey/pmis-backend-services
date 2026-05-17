"""JWT decode for pmis-masters-management.

Verify-only: this service does NOT issue tokens. Token minting lives in
pmis-user-management. masters-svc decodes incoming Bearer tokens locally
using the shared SECRET_KEY (Decision 7, Q11).

WARNING: This file is duplicated across services per PLAN.md §6.1. The
canonical declaration (with token-issuance helpers) will live in
  services/pmis-user-management/app/core/security.py
once user-svc is ported. The DECODE portion below MUST stay byte-identical
across services or JWT verification breaks. Keep in sync by hand until
tools/check_canonical_drift.py is wired.

Expected claim shape (issued by user-svc):
  { sub: <user_id>, user_id: <user_id>, email: <str>, jti: <uuid>, iat, exp }
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from jose import ExpiredSignatureError, JWTError, jwt

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode + verify a JWT. Returns the claims dict on success, None otherwise.

    Never raises — caller treats None as anonymous request state.
    """
    if not token:
        return None
    try:
        claims = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        return claims
    except ExpiredSignatureError:
        logger.debug("JWT decode: expired token")
        return None
    except JWTError as exc:
        logger.debug("JWT decode failed: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("JWT decode raised unexpectedly: %s", exc)
        return None


def extract_bearer_token(authorization_header: Optional[str]) -> Optional[str]:
    """Pull the raw token out of an `Authorization: Bearer <token>` header."""
    if not authorization_header:
        return None
    parts = authorization_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
