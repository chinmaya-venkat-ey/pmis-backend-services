"""POST /notification/cron/daily-digest — DevOps-driven daily-digest cron.

Auth: X-Cron-Secret header that must match settings.cron_shared_secret.
Empty secret in settings disables the endpoint (503).

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\routes\\cron_routes.py:1-104
with service-layer extraction per Q8.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, status

from app.config import settings
from app.controllers.cron_controller import CronController
from app.core.errors import CronUnauthorizedError
from app.dependencies import get_cron_controller
from app.schemas.digest import DigestRequest, DigestResponse


router = APIRouter(prefix="/cron", tags=["cron"])


def _verify_cron_secret(
    x_cron_secret: Optional[str] = Header(default=None, alias="X-Cron-Secret"),
) -> None:
    """Gate the cron endpoint via shared-secret header.

    Failure modes:
      - 503 when CRON_SHARED_SECRET is not configured (endpoint not deployed)
      - 401 when the header is missing or doesn't match
    """
    expected = (settings.cron_shared_secret or "").strip()
    if not expected:
        # Returning 503 distinguishes "not configured" from "wrong secret".
        # We construct a CronUnauthorizedError subclass with 503 inline so
        # the error_handler emits a sensible envelope.
        raise CronUnauthorizedError(
            "Cron endpoint disabled: CRON_SHARED_SECRET is not configured",
            code="CRON_NOT_CONFIGURED",
            details={"hint": "Set CRON_SHARED_SECRET in the notification-svc env"},
        )
    if not x_cron_secret or x_cron_secret != expected:
        raise CronUnauthorizedError(
            "Invalid or missing X-Cron-Secret header",
            code="CRON_SECRET_MISMATCH",
        )


@router.post(
    "/daily-digest",
    response_model=DigestResponse,
    status_code=status.HTTP_200_OK,
    summary="Send the daily deadline-digest emails",
    description=(
        "Driven by an external cron (DevOps host crontab posts here once a "
        "day). Scans milestones + activities whose end_date is within "
        "DEADLINE_WINDOW_DAYS (default 5) OR past due, groups them per "
        "responsible user (org_admin / project_admin / project_member "
        "scoped to the project), and dispatches one email per user. Skips "
        "completed items, closed projects, soft-deleted rows, and "
        "inactive / soft-deleted users."
    ),
)
def daily_digest(
    payload: DigestRequest = Body(default_factory=DigestRequest),
    controller: CronController = Depends(get_cron_controller),
    _auth: None = Depends(_verify_cron_secret),
) -> DigestResponse:
    return controller.run_daily_digest(payload)
