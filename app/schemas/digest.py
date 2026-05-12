"""Pydantic schemas for the daily-digest cron endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DigestResponse(BaseModel):
    """Summary of what one daily-digest run did."""
    model_config = ConfigDict(populate_by_name=True)

    ran_at: datetime = Field(..., alias="ranAt")
    users_notified: int = Field(..., alias="usersNotified")
    emails_sent: int = Field(..., alias="emailsSent")
    emails_failed: int = Field(..., alias="emailsFailed")
    items_aggregated: int = Field(..., alias="itemsAggregated")


class DigestRequest(BaseModel):
    """Optional body for cron callers that want to override defaults.

    All fields are optional — DevOps's cron normally posts an empty
    body and lets the defaults (today / settings.deadline_window_days)
    apply. The body exists so a re-run / replay tool can target a
    specific date.
    """
    today: Optional[str] = Field(
        None,
        description=(
            "ISO date (YYYY-MM-DD). Overrides the cron's notion of "
            "'today'. Useful for replaying yesterday's run."
        ),
    )
    window_days: Optional[int] = Field(
        None, ge=0, le=30, alias="windowDays",
        description=(
            "Override DEADLINE_WINDOW_DAYS for this single call. "
            "Range 0-30 days. Default: settings.deadline_window_days."
        ),
    )

    model_config = ConfigDict(populate_by_name=True)
