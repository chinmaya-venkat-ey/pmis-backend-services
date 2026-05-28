"""Pydantic schemas for master reference tables."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    points: Optional[int] = Field(None, ge=-100, le=100)
    label: Optional[str] = Field(None, min_length=1, max_length=100)


class SeverityLevelInput(BaseModel):
    level: int = Field(..., ge=0, le=4)
    points: int = Field(..., ge=-100, le=100)
    label: str = Field(..., min_length=1, max_length=100)


class SeverityMasterSetRequest(BaseModel):
    levels: List[SeverityLevelInput] = Field(
        ...,
        min_length=1,
        description="Provide all 5 levels (0-4) to fully replace, or fewer to partial-replace.",
    )


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
