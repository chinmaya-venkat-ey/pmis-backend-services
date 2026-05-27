"""Pydantic schemas for Metric Observation APIs — Phase 4."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Band count sub-schemas
# ---------------------------------------------------------------------------

class BandCountRequest(BaseModel):
    band_id: str
    band_label: str
    unit_count: Decimal = Field(..., ge=0, description="Number of units (days/instances) in this band")


class BandCountResponse(BaseModel):
    id: str
    observation_id: str
    band_id: str
    band_label: str
    unit_count: Decimal
    created_at: Optional[datetime]
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Observation requests
# ---------------------------------------------------------------------------

class ObservationCreateRequest(BaseModel):
    metric_key: str
    period_start: date
    period_end: date
    observed_value: Decimal
    observed_unit: str
    baseline_used: Optional[Decimal] = None
    excluded_from_sla: bool = False
    exclusion_reason: Optional[str] = Field(None, max_length=100)
    additional_inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context inputs: {num_applications} for WAC, {planned_downtime_minutes} for uptime, etc.",
    )
    data_source: Optional[str] = Field(None, max_length=30)
    # Convenience: inline band counts for band_accumulation SLAs
    band_counts: List[BandCountRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "ObservationCreateRequest":
        if self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        if self.excluded_from_sla and not self.exclusion_reason:
            raise ValueError("exclusion_reason is required when excluded_from_sla is True")
        return self


class ObservationUpdateRequest(BaseModel):
    """Allowed only while observation is PENDING."""
    observed_value: Optional[Decimal] = None
    observed_unit: Optional[str] = None
    baseline_used: Optional[Decimal] = None
    additional_inputs: Optional[Dict[str, Any]] = None
    data_source: Optional[str] = Field(None, max_length=30)


class ObservationExcludeRequest(BaseModel):
    """Set or clear the exclusion flag. Gap 6 fix: reversal supported."""
    excluded: bool
    exclusion_reason: Optional[str] = Field(None, max_length=100)

    @model_validator(mode="after")
    def _reason_required(self) -> "ObservationExcludeRequest":
        if self.excluded and not self.exclusion_reason:
            raise ValueError("exclusion_reason is required when excluding an observation")
        return self


class BandCountSubmitRequest(BaseModel):
    """Submit (or replace) band counts for a PENDING band_accumulation observation."""
    band_counts: List[BandCountRequest] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Observation responses
# ---------------------------------------------------------------------------

class ObservationResponse(BaseModel):
    id: str
    sla_id: str
    metric_key: str
    period_start: date
    period_end: date
    observed_value: Decimal
    observed_unit: str
    baseline_used: Optional[Decimal]
    excluded_from_sla: bool
    exclusion_reason: Optional[str]
    additional_inputs: Dict[str, Any]
    data_source: Optional[str]
    submitted_by: Optional[str]
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    status: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    model_config = {"from_attributes": True}


class ObservationDetailResponse(ObservationResponse):
    """Single observation with its band counts."""
    band_counts: List[BandCountResponse] = Field(default_factory=list)
