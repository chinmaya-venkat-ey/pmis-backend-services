"""
ProjectCode generator.

Format: UIDAI-PRYYMMDDHHMMSS  (in IST / Asia/Kolkata).

Example: UIDAI-PR240421143052

On collision (two projects created in the same second), retries by
switching to millisecond precision: UIDAI-PRYYMMDDHHMMSSmmm.

Called from project create + version create services (any code path that
inserts a new row in `projects` needs a fresh ProjectCode).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

# IST has no DST -- fixed UTC+5:30. Using a fixed-offset timezone avoids the
# need for the IANA `tzdata` package on Windows (which doesn't ship it by
# default). If you later need DST-aware behavior, swap to ZoneInfo.
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30), name="IST")

_PREFIX = "UIDAI-PR"
_MAX_RETRIES = 6


def _format_seconds(now: datetime) -> str:
    return f"{_PREFIX}{now.strftime('%y%m%d%H%M%S')}"


def _format_milliseconds(now: datetime) -> str:
    ms = now.microsecond // 1000
    return f"{_PREFIX}{now.strftime('%y%m%d%H%M%S')}{ms:03d}"


def generate_project_code(db: Session) -> str:
    """
    Generate a unique ProjectCode, checking the DB for collisions.

    Strategy:
      - First attempt: seconds-precision (UIDAI-PRYYMMDDHHMMSS).
      - On collision: milliseconds-precision, up to 5 retries.
      - Raises RuntimeError if still colliding after retries (extremely rare;
        requires >1 project insert per millisecond consistently).

    Safe to call inside an open transaction; does NOT commit.
    """
    # Local import to avoid circulars at module-load time.
    from ..infrastructure.db.models.project import ProjectModel

    now = datetime.now(IST)

    # First attempt: seconds-level.
    code = _format_seconds(now)
    if db.query(ProjectModel.id).filter(ProjectModel.project_code == code).first() is None:
        return code

    # Retry with millisecond precision.
    for _ in range(_MAX_RETRIES):
        now = datetime.now(IST)
        code = _format_milliseconds(now)
        if db.query(ProjectModel.id).filter(ProjectModel.project_code == code).first() is None:
            return code
        time.sleep(0.001)  # wait 1ms then retry

    raise RuntimeError(
        "Could not allocate a unique ProjectCode after multiple attempts. "
        "This indicates extreme concurrent write load; please retry the request."
    )
