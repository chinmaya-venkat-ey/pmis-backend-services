"""Pydantic schemas for the Critical Path Analysis (CPA) APIs.

API 1 — GET /api/v3/projects/{project_id}/critical-path/dependencies
  Response: CpaDependencyResponse

API 2 — POST /api/v3/projects/{project_id}/critical-path/analysis
  Request:  CpaAnalysisRequest  (optional per-activity duration overrides)
  Response: CpaAnalysisResponse
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

class CpaDependsOn(BaseModel):
    activity_id: str
    display_code: str
    name: str


class CpaDependencyRow(BaseModel):
    activity_id: str
    display_code: str
    name: str
    milestone_id: str
    milestone_display_code: str
    milestone_name: str
    days_needed: int
    days_delayed: int
    effective_duration: int
    status: Optional[str]
    depends_on: List[CpaDependsOn]


class CpaDependencyResponse(BaseModel):
    project_id: str
    total_activities: int
    dependencies: List[CpaDependencyRow]


# ---------------------------------------------------------------------------
# Analysis request — allows FE/planner to override durations (what-if)
# ---------------------------------------------------------------------------

class CpaActivityOverride(BaseModel):
    activity_id: str
    days_needed: Optional[int] = None
    days_delayed: Optional[int] = None


class CpaAnalysisRequest(BaseModel):
    overrides: Optional[List[CpaActivityOverride]] = None


# ---------------------------------------------------------------------------
# Analysis response
# ---------------------------------------------------------------------------

class CpaActivitySchedule(BaseModel):
    activity_id: str
    display_code: str
    name: str
    milestone_id: str
    milestone_display_code: str
    milestone_name: str
    status: Optional[str]
    days_needed: int
    days_delayed: int
    effective_duration: int
    early_start: int
    early_finish: int
    late_start: int
    late_finish: int
    slack: int
    on_critical_path: bool


class CpaFlowNode(BaseModel):
    id: str
    label: str
    display_code: str
    name: str
    milestone_display_code: str
    effective_duration: int
    early_start: int
    early_finish: int
    late_start: int
    late_finish: int
    slack: int
    on_critical_path: bool
    status: Optional[str]
    position: Dict[str, Any]


class CpaFlowEdge(BaseModel):
    id: str
    source: str
    target: str
    on_critical_path: bool


class CpaMetadata(BaseModel):
    total_project_days: int
    activities_on_critical_path: int
    total_activities: int
    total_buffer_slack: int
    project_delay_days: int
    has_cycle: bool


class CpaAnalysisResponse(BaseModel):
    project_id: str
    metadata: CpaMetadata
    critical_path: List[str]
    activity_schedule: List[CpaActivitySchedule]
    flow_diagram: Dict[str, Any]
