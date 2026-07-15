"""Dashboard snapshot cron route.

A single POST that the scheduler calls (daily) to persist the current
global KPI values so the summary dashboard can derive month-over-month
``delta`` strings and 6-month ``spark`` arrays.

Unlike the rest of the dashboard surface this route is NOT gated by a user
JWT / ``projects:read_all`` — it's machine-to-machine. It authenticates
with a shared secret sent as the ``X-Cron-Secret`` header, matched against
``settings.cron_shared_secret`` (mirrors the notification service's cron
convention). A blank configured secret disables the endpoint entirely.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import ForbiddenError
from app.db import get_db
from app.services.dashboard_service import _ist_today
from app.services.dashboard_snapshot_service import DashboardSnapshotService
from app.services.dashboard_view_service import DashboardViewService


router = APIRouter(prefix="/dashboard/cron", tags=["dashboard-cron"])


@router.post(
    "/snapshot",
    summary="Persist today's dashboard KPI values (shared-secret gated)",
    description=(
        "Machine-to-machine. Computes the current global KPI values and "
        "upserts one snapshot row per metric for today's date, backing the "
        "summary dashboard's delta/spark fields. Requires the "
        "`X-Cron-Secret` header to match the configured secret; a blank "
        "configured secret disables the endpoint (403)."
    ),
)
def run_dashboard_snapshot(
    db: Annotated[Session, Depends(get_db)],
    x_cron_secret: Annotated[Optional[str], Header(alias="X-Cron-Secret")] = None,
) -> Dict[str, Any]:
    expected = (settings.cron_shared_secret or "").strip()
    if not expected or (x_cron_secret or "").strip() != expected:
        raise ForbiddenError("Invalid or missing cron secret.")

    today = _ist_today()
    metrics = DashboardViewService(db).current_global_metrics()
    written = DashboardSnapshotService(db).write_snapshot(
        captured_date=today, metrics=metrics,
    )
    return {
        "capturedDate": today.isoformat(),
        "scope": "global",
        "metricsWritten": written,
    }
