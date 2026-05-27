"""Pydantic schemas for Contract and ContractPhase — request bodies and wire responses."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

VALID_CONTRACT_STATUSES = {"ACTIVE", "PROBATION", "SUSPENDED", "EXPIRED", "TERMINATED"}


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

class ContractCreateRequest(BaseModel):
    contract_ref: str = Field(..., max_length=100)
    title: str = Field(..., max_length=500)
    vendor_name: str = Field(..., max_length=255)
    start_date: date
    end_date: Optional[date] = None
    total_value: Optional[Decimal] = None
    currency: str = Field("INR", max_length=10)
    quarterly_ld_cap_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _end_after_start(self) -> "ContractCreateRequest":
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ContractUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    vendor_name: Optional[str] = Field(None, max_length=255)
    end_date: Optional[date] = None
    total_value: Optional[Decimal] = None
    currency: Optional[str] = Field(None, max_length=10)
    status: Optional[str] = None
    quarterly_ld_cap_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _valid_status(self) -> "ContractUpdateRequest":
        if self.status and self.status not in VALID_CONTRACT_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(sorted(VALID_CONTRACT_STATUSES))}"
            )
        return self


class ContractResponse(BaseModel):
    id: str
    contract_ref: str
    title: str
    vendor_name: str
    start_date: date
    end_date: Optional[date]
    total_value: Optional[Decimal]
    currency: str
    status: str
    quarterly_ld_cap_percent: Optional[Decimal]
    metadata: Dict[str, Any]
    created_by: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, row) -> "ContractResponse":
        return cls(
            id=row.id,
            contract_ref=row.contract_ref,
            title=row.title,
            vendor_name=row.vendor_name,
            start_date=row.start_date,
            end_date=row.end_date,
            total_value=row.total_value,
            currency=row.currency,
            status=row.status,
            quarterly_ld_cap_percent=row.quarterly_ld_cap_percent,
            metadata=row.metadata_ or {},
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ContractListResponse(BaseModel):
    items: List[ContractResponse]
    total: int
    offset: int
    page_size: int


# ---------------------------------------------------------------------------
# ContractPhase
# ---------------------------------------------------------------------------

class PhaseCreateRequest(BaseModel):
    phase_name: str = Field(..., max_length=255)
    start_date: date
    end_date: Optional[date] = None
    is_active: bool = True

    @model_validator(mode="after")
    def _end_after_start(self) -> "PhaseCreateRequest":
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class PhaseUpdateRequest(BaseModel):
    phase_name: Optional[str] = Field(None, max_length=255)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None


class PhaseResponse(BaseModel):
    id: str
    contract_id: str
    phase_name: str
    start_date: date
    end_date: Optional[date]
    is_active: bool
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}
