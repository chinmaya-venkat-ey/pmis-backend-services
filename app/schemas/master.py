"""Pydantic schemas for master reference tables."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- Enum catalog
# Single source of truth for all dropdown values used in SLA onboarding.
# These are tied to evaluation logic — new values require eval engine changes too.

SLA_ENUMS: Dict[str, List[Dict[str, str]]] = {
    "measurement_interval": [
        {"code": "DAILY",     "label": "Daily"},
        {"code": "WEEKLY",    "label": "Weekly"},
        {"code": "MONTHLY",   "label": "Monthly"},
        {"code": "QUARTERLY", "label": "Quarterly"},
        {"code": "ONE_TIME",  "label": "One-time (milestone / validation event)"},
    ],
    "reporting_interval": [
        {"code": "WEEKLY",    "label": "Weekly"},
        {"code": "MONTHLY",   "label": "Monthly"},
        {"code": "QUARTERLY", "label": "Quarterly"},
        {"code": "ANNUAL",    "label": "Annual"},
    ],
    "baseline_type": [
        {"code": "STATIC",  "label": "Static — fixed target, never changes"},
        {"code": "ROLLING", "label": "Rolling — baseline updates when performance improves"},
    ],
    "compound_metric_rule": [
        {"code": "INDEPENDENT", "label": "Independent — each metric's LD computed and summed separately"},
        {"code": "COMBINED",    "label": "Combined — all metrics must breach together"},
    ],
    "ld_aggregation_method": [
        {"code": "SUM",      "label": "Sum — add all period LDs"},
        {"code": "MAX",      "label": "Max — take the highest period LD"},
        {"code": "WEIGHTED", "label": "Weighted — weighted average of period LDs"},
    ],
    "ld_computation_base": [
        {"code": "QUARTERLY_PAYMENT", "label": "Quarterly payment due to vendor"},
        {"code": "ANNUAL_PAYMENT",    "label": "Annual contract value"},
        {"code": "FIXED_AMOUNT",      "label": "Fixed rupee amount (defined in parameters)"},
    ],
    "guard_action": [
        {"code": "EXCLUDE",   "label": "Exclude — drop observation from LD calculation"},
        {"code": "SUSPEND",   "label": "Suspend — halt LD computation for the period"},
        {"code": "PROBATION", "label": "Probation — mark period as non-payable"},
    ],
    "metric_direction": [
        {"code": "LOWER_BETTER",  "label": "Lower is better (e.g. error rate)"},
        {"code": "HIGHER_BETTER", "label": "Higher is better (e.g. uptime)"},
    ],
    "guard_operator": [
        {"code": "LT",  "label": "Less than (<)"},
        {"code": "LTE", "label": "Less than or equal (≤)"},
        {"code": "GT",  "label": "Greater than (>)"},
        {"code": "GTE", "label": "Greater than or equal (≥)"},
        {"code": "EQ",  "label": "Equal to (=)"},
        {"code": "NEQ", "label": "Not equal to (≠)"},
    ],
    "sla_status": [
        {"code": "ACTIVE",   "label": "Active"},
        {"code": "INACTIVE", "label": "Inactive"},
    ],
}


# --------------------------------------------------------------------------- Contract Types

class ContractTypeCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20, pattern=r'^[A-Z0-9]+$')
    display_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class ContractTypeUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None


class ContractTypeResponse(BaseModel):
    code: str
    display_name: str
    description: Optional[str] = None
    is_active: bool
    model_config = {"from_attributes": True}


# --------------------------------------------------------------------------- Data Fields

class DataFieldCreateRequest(BaseModel):
    field_name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(..., min_length=1, max_length=200)
    data_type: str = Field(..., pattern=r"^(INTEGER|DECIMAL|DATE|BOOLEAN)$")
    unit: str = Field(..., max_length=50)
    example_value: Optional[str] = Field(None, max_length=50)
    applicable_to: Optional[List[str]] = Field(
        None,
        description="Contract type codes this field applies to. NULL = applies to all.",
    )


class DataFieldUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=200)
    unit: Optional[str] = Field(None, max_length=50)
    example_value: Optional[str] = Field(None, max_length=50)
    applicable_to: Optional[List[str]] = None
    is_active: Optional[bool] = None


class DataFieldResponse(BaseModel):
    field_name: str
    display_name: str
    data_type: str
    unit: str
    example_value: Optional[str] = None
    applicable_to: Optional[List[str]] = None
    is_active: bool
    model_config = {"from_attributes": True}


# --------------------------------------------------------------------------- Severity Master

class SeverityLevelResponse(BaseModel):
    id: str
    project_id: str
    level: int
    points: int
    label: str
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class SeverityLevelUpdateRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {"points": 6, "label": "Sev 3 — major breach (revised)"}
        }
    }
    points: Optional[int] = Field(None, ge=-100, le=100)
    label: Optional[str] = Field(None, min_length=1, max_length=100)


class SeverityLevelInput(BaseModel):
    # Levels are open-ended — the RFP uses 0-4 but a project can extend the
    # ladder upward (or downward) as needed; PATCH severity-master/{level}
    # creates whatever level you reference. No upper or lower bound enforced.
    level: int = Field(..., ge=0)
    points: int = Field(..., ge=-100, le=100)
    label: str = Field(..., min_length=1, max_length=100)


class SeverityMasterSetRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "levels": [
                    {"level": 0, "points": -2, "label": "Sev 0 — on target / better than target"},
                    {"level": 1, "points":  2, "label": "Sev 1 — minor breach"},
                    {"level": 2, "points":  4, "label": "Sev 2 — moderate breach"},
                    {"level": 3, "points":  6, "label": "Sev 3 — major breach"},
                    {"level": 4, "points":  8, "label": "Sev 4 — significant breach"},
                ]
            }
        }
    }
    levels: List[SeverityLevelInput] = Field(
        ...,
        min_length=1,
        description="Provide all 5 levels (0-4) to fully replace, or fewer to partial-replace.",
    )


# --------------------------------------------------------------------------- Project LD Bands

# Symmetric to SeverityMaster, but maps accumulated points -> LD%. Used by the
# evaluator after severity_master gives it level -> points; the two together
# can fully replace the RFP-default scoring baked into point_accumulation.py.

from decimal import Decimal as _Decimal  # local alias to avoid touching top imports


class LdBandResponse(BaseModel):
    id: str
    project_id: str
    points_threshold: _Decimal
    ld_percent: _Decimal
    label: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class LdBandInput(BaseModel):
    points_threshold: _Decimal = Field(
        ...,
        description="Inclusive lower bound. Evaluator picks the highest threshold "
                    "the accumulated points meet.",
    )
    ld_percent: _Decimal = Field(..., ge=0, le=100)
    label: Optional[str] = Field(None, max_length=100)


class LdBandUpdateRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {"points_threshold": 5, "ld_percent": "2.5",
                        "label": "5 points — 2.5% LD"}
        }
    }
    points_threshold: Optional[_Decimal] = None
    ld_percent: Optional[_Decimal] = Field(None, ge=0, le=100)
    label: Optional[str] = Field(None, max_length=100)


class LdBandSetRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "bands": [
                    {"points_threshold": 0, "ld_percent": 0,  "label": "0 points — no LD"},
                    {"points_threshold": 2, "ld_percent": 1,  "label": "2 points — 1% LD"},
                    {"points_threshold": 4, "ld_percent": 2,  "label": "4 points — 2% LD"},
                    {"points_threshold": 6, "ld_percent": 3,  "label": "6 points — 3% LD"},
                    {"points_threshold": 8, "ld_percent": 4,  "label": "8+ points — 4% LD"},
                ]
            }
        }
    }
    bands: List[LdBandInput] = Field(
        ...,
        min_length=1,
        description="Replaces all existing LD bands for the project.",
    )


# --------------------------------------------------------------------------- SLA Categories

class SlaCategoryResponse(BaseModel):
    """User-facing SLA category. Replaces formula_type as the picker label.

    ``formula_type`` is included on the response so the FE knows which engine
    will run behind the scenes — useful for showing a hint ("uses
    point_accumulation under the hood") without making the user pick it.
    """
    code: str
    display_name: str
    formula_type: str
    description: Optional[str] = None
    sort_order: int
    is_active: bool
    model_config = {"from_attributes": True}


# --------------------------------------------------------------------------- Formula Library

_OBS_INPUT_TYPE: Dict[str, str] = {
    "point_accumulation": "single_value",
    "fixed_escalation":   "single_value",
    "band_accumulation":  "band_counts",
    "wac":                "wac_breakdown",
}


class FormulaLibraryResponse(BaseModel):
    id: str
    formula_type: str
    display_name: str
    description: Optional[str] = None
    parameter_schema: Dict[str, Any]
    requires_bands: bool
    requires_lookup: bool
    observation_input_type: str
    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_obs_type(cls, obj: Any) -> "FormulaLibraryResponse":
        return cls(
            id=obj.id,
            formula_type=obj.formula_type,
            display_name=obj.display_name,
            description=obj.description,
            parameter_schema=obj.parameter_schema,
            requires_bands=obj.requires_bands,
            requires_lookup=obj.requires_lookup,
            observation_input_type=_OBS_INPUT_TYPE.get(obj.formula_type, "single_value"),
        )
