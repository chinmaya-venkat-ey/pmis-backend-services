"""Human-readable code generators for project_code (and similar identifiers).

Format: `UIDAI-PR{YYMMDDHHMMSS-IST}` — used for projects.
        `MS-{slug}-{YYMMDDHHMMSS-IST}` — milestones.
        `AC-{slug}-{YYMMDDHHMMSS-IST}` — activities.

Ported from C:\\Programming\\PMIS\\PMIS-OpenProject\\app\\shared\\code_generators.py.
"""
from __future__ import annotations

import re
from datetime import datetime

from app.utilities.timezones import IST


_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _slug(name: str) -> str:
    cleaned = _NON_ALNUM.sub("", (name or "").lower())
    return cleaned[:4] or "item"


def _ts(now: datetime | None = None) -> str:
    moment = (now or datetime.now(IST)).astimezone(IST)
    return moment.strftime("%y%m%d%H%M%S") + f"{moment.microsecond // 1000:03d}"


def generate_project_code(now: datetime | None = None) -> str:
    return f"UIDAI-PR{_ts(now)}"


def generate_milestone_code(name: str, now: datetime | None = None) -> str:
    return f"MS-{_slug(name)}-{_ts(now)}"


def generate_activity_code(name: str, now: datetime | None = None) -> str:
    return f"AC-{_slug(name)}-{_ts(now)}"


def generate_vendor_code(name: str, now: datetime | None = None) -> str:
    return f"VD-{_slug(name)}-{_ts(now)}"
