"""DevOps-driven cron endpoints for notification-service.

POST /api/v1/notifications/cron/daily-digest
    Scans for milestones / activities ending within the configured
    window (or past due), groups them per responsible user
    (org_admin / project_admin / project_member on the project), and
    sends one email per user via the existing email_service.

Auth: header ``X-Cron-Secret: <value>`` that must match
``settings.cron_shared_secret``. Empty secret in settings disables
the endpoint (returns 503) — keeps boot-time safe defaults.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.schemas.digest import DigestRequest, DigestResponse
from app.services.digest_service import run_daily_digest
from app.services.email_service import EmailService, get_email_service


router = APIRouter(prefix="/notifications/cron", tags=["Cron"])


def _verify_cron_secret(
    x_cron_secret: Optional[str] = Header(default=None, alias="X-Cron-Secret"),
) -> None:
    """Gate: require the secret to be configured AND to match the
    header. We intentionally distinguish the two failure modes:
    - 503 when the secret env var is unset (endpoint not deployed yet)
    - 401 when the header is missing or wrong (caller misconfigured)
    """
    expected = (settings.cron_shared_secret or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Cron endpoint disabled: CRON_SHARED_SECRET is not "
                "configured on this notification-service instance."
            ),
        )
    if not x_cron_secret or x_cron_secret != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Cron-Secret header.",
        )


def _parse_today(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid 'today' format {raw!r}; expected ISO date "
                "(YYYY-MM-DD)."
            ),
        ) from exc


@router.post(
    "/daily-digest",
    response_model=DigestResponse,
    status_code=status.HTTP_200_OK,
    summary="Send the daily deadline-digest email to every responsible user",
    description=(
        "Driven by an external cron (DevOps host crontab posts here "
        "once a day). Scans milestones + activities whose end_date is "
        "within DEADLINE_WINDOW_DAYS (default 5) OR past due, groups "
        "them per responsible user (org_admin / project_admin / "
        "project_member scoped to the project), and dispatches one "
        "email per user. Skips completed items, closed projects, "
        "soft-deleted rows, and inactive / soft-deleted users."
    ),
)
def daily_digest(
    payload: DigestRequest = Body(default_factory=DigestRequest),
    db: Session = Depends(get_db),
    email_service: EmailService = Depends(get_email_service),
    _auth: None = Depends(_verify_cron_secret),
) -> DigestResponse:
    today = _parse_today(payload.today)
    summary = run_daily_digest(
        db=db,
        email_service=email_service,
        today=today,
        window_days=payload.window_days,
    )
    return DigestResponse(
        ran_at=summary.ran_at,
        users_notified=summary.users_notified,
        emails_sent=summary.emails_sent,
        emails_failed=summary.emails_failed,
        items_aggregated=summary.items_aggregated,
    )
