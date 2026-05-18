"""Human-readable code generators for vendor_code and similar identifiers.

Format: `VD-{slug}-{YYMMDDHHMMSSMMM-IST}`
  - Slug: first 4 alphanumeric chars of the vendor name (lowercased).
  - Timestamp: IST (UTC+05:30) at creation time, 15-digit (12 + 3ms).
"""
from __future__ import annotations

import re
from datetime import datetime

from app.utilities.timezones import IST


_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _slug(name: str) -> str:
    cleaned = _NON_ALNUM.sub("", (name or "").lower())
    return cleaned[:4] or "vndr"


def _ts(now: datetime | None = None) -> str:
    moment = (now or datetime.now(IST)).astimezone(IST)
    return moment.strftime("%y%m%d%H%M%S") + f"{moment.microsecond // 1000:03d}"


def generate_vendor_code(name: str, now: datetime | None = None) -> str:
    return f"VD-{_slug(name)}-{_ts(now)}"
