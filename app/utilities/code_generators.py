"""Human-readable code generators for user_code (and similar identifiers).

Format: `US-{slug}-{YYMMDDHHMMSS-IST}`
  - Slug: first 4 alphanumeric chars of the user's name (lowercased; falls
    back to "user" if name is missing).
  - Timestamp: IST (UTC+05:30) at creation time, fixed-width 12-digit.

Examples:
  US-alic-260514101530   (Alice Lee, 2026-05-14 10:15:30 IST)
  US-user-260514101533   (no name provided)

Ported from C:\\Programming\\PMIS\\PMIS-user-management\\app\\shared\\code_generators.py.
"""
from __future__ import annotations

import re
from datetime import datetime

from app.utilities.timezones import IST


_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _slug(name: str) -> str:
    """Lowercase + strip non-alphanumerics + take first 4 chars."""
    cleaned = _NON_ALNUM.sub("", (name or "").lower())
    return cleaned[:4] or "user"


def generate_user_code(name: str, now: datetime | None = None) -> str:
    """Build a user_code string. `now` is overridable for deterministic tests."""
    moment = (now or datetime.now(IST)).astimezone(IST)
    timestamp = moment.strftime("%y%m%d%H%M%S")
    return f"US-{_slug(name)}-{timestamp}"
