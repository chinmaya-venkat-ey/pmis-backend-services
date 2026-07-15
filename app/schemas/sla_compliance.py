"""Schemas for the SLA compliance surface (observation input)."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field


class ObservationRequest(BaseModel):
    """Record an observed value for an SLA mapping (the recorded-observation
    path for %/count/WAC/resource SLAs). ``observed_value`` shape follows the
    SLA's formula: a number, a list (daily values), or an object (band counts
    / WAC breakdown)."""

    mapping_id: str = Field(..., description="SLA activity-mapping id")
    observed_value: Any = Field(..., description="Observed value: number | list | object")
    metric_key: Optional[str] = Field(default=None)
    period_start: Optional[date] = Field(default=None)
    period_end: Optional[date] = Field(default=None)
    note: Optional[str] = Field(default=None, max_length=1000)
