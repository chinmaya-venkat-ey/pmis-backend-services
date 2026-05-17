"""Daily-digest cron schemas (Pydantic v2).

POST /notification/cron/daily-digest is invoked by devops's external cron
with an X-Cron-Secret header. notification-svc walks cross-schema users +
projects + milestones + activities to find recipients and upcoming deadlines.

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\schemas\\digest.py:1-45.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field


class DigestRequest(BaseModel):
    """Optional body for cron callers that want to override defaults.

    DevOps's cron normally posts an empty body and lets the defaults apply
    (today / settings.deadline_window_days). The body exists so a re-run /
    replay tool can target a specific date.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )

    today: Annotated[
        Optional[str],
        Field(
            default=None,
            description="ISO date (YYYY-MM-DD). Overrides cron's notion of 'today' (useful for replay).",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ]
    window_days: Annotated[
        Optional[int],
        Field(
            default=None,
            ge=0,
            le=30,
            alias="windowDays",
            description="Override DEADLINE_WINDOW_DAYS for this single call (0–30 days).",
        ),
    ]


class DigestResponse(BaseModel):
    """Summary of one daily-digest run."""

    model_config = ConfigDict(populate_by_name=True)

    ran_at: datetime = Field(..., alias="ranAt", description="When this run started (IST timestamp)")
    users_notified: int = Field(..., alias="usersNotified", description="Distinct recipients emailed")
    emails_sent: int = Field(..., alias="emailsSent", description="Email-send attempts that succeeded")
    emails_failed: int = Field(..., alias="emailsFailed", description="Email-send attempts that failed")
    items_aggregated: int = Field(
        ..., alias="itemsAggregated", description="Total deadline items rolled into outgoing emails"
    )
