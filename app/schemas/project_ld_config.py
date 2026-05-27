"""Pydantic schemas for ProjectLdConfig — LD financial terms per project."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

VALID_LD_STATUSES = {"ACTIVE", "PROBATION", "SUSPENDED", "EXPIRED", "TERMINATED"}


class ScoringConfigRequest(BaseModel):
    """MSAP/PMU scoring: severity → points → LD%."""
    severity_points_map: List[Dict[str, Any]]
    points_ld_map: List[Dict[str, Any]]
    applies_to: List[str] = Field(default=["point_accumulation", "wac"])


class ScoringConfigResponse(BaseModel):
    severity_points_map: List[Dict[str, Any]]
    points_ld_map: List[Dict[str, Any]]
    scoring_applies_to: Optional[List[str]]


class ProjectLdConfigCreateRequest(BaseModel):
    contract_ref: str = Field(..., max_length=100)
    total_value: Optional[Decimal] = None
    currency: str = Field("INR", max_length=10)
    quarterly_ld_cap_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    scoring_config: Optional[ScoringConfigRequest] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProjectLdConfigUpdateRequest(BaseModel):
    contract_ref: Optional[str] = Field(None, max_length=100)
    total_value: Optional[Decimal] = None
    currency: Optional[str] = Field(None, max_length=10)
    quarterly_ld_cap_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    ld_status: Optional[str] = None
    scoring_config: Optional[ScoringConfigRequest] = None
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _valid_status(self) -> "ProjectLdConfigUpdateRequest":
        if self.ld_status and self.ld_status not in VALID_LD_STATUSES:
            raise ValueError(
                f"ld_status must be one of: {', '.join(sorted(VALID_LD_STATUSES))}"
            )
        return self


class ProjectLdConfigResponse(BaseModel):
    id: str
    project_id: str
    contract_ref: str
    total_value: Optional[Decimal]
    currency: str
    quarterly_ld_cap_percent: Optional[Decimal]
    ld_status: str
    scoring_config: Optional[ScoringConfigResponse] = None
    metadata: Dict[str, Any]
    created_by: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, row) -> "ProjectLdConfigResponse":
        scoring = None
        if row.severity_points_map is not None:
            scoring = ScoringConfigResponse(
                severity_points_map=row.severity_points_map,
                points_ld_map=row.points_ld_map or [],
                scoring_applies_to=row.scoring_applies_to,
            )
        return cls(
            id=row.id,
            project_id=row.project_id,
            contract_ref=row.contract_ref,
            total_value=row.total_value,
            currency=row.currency,
            quarterly_ld_cap_percent=row.quarterly_ld_cap_percent,
            ld_status=row.ld_status,
            scoring_config=scoring,
            metadata=row.metadata_ or {},
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
