"""JWT decode for pmis-project-management — verify-only.

Duplicates services/pmis-masters-management/app/core/security.py. project-svc
does NOT issue tokens; user-svc is the canonical issuer. Keep decode logic
byte-identical with peers or JWT verification breaks.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from jose import ExpiredSignatureError, JWTError, jwt

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
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
    if not authorization_header:
        return None
    parts = authorization_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
