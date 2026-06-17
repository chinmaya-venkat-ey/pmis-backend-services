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
    # Cross-project predecessor flags (additive; default False/None keeps the
    # wire backward-compatible for same-project deps).
    cross_project: bool = False
    project_name: Optional[str] = None


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
    status: Optional[str] = None
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
# Critical path — each activity on the path with name + duration
# ---------------------------------------------------------------------------

class CpaCriticalPathActivity(BaseModel):
    display_code: str
    name: str
    duration: int          # effective_duration (days_needed + days_delayed)
    days_needed: int
    days_delayed: int


# ---------------------------------------------------------------------------
# Per-activity calculation step detail (one formula row)
# ---------------------------------------------------------------------------

class CpaCalcDetail(BaseModel):
    formula: str           # symbolic form  e.g. "max(EF[A1.1], EF[A1.2]) + 1"
    substituted: str       # values plugged in  e.g. "max(5, 3) + 1"
    result: int
    note: Optional[str] = None   # extra plain-English note


class CpaCalculationSteps(BaseModel):
    early_start: CpaCalcDetail
    early_finish: CpaCalcDetail
    late_finish: CpaCalcDetail
    late_start: CpaCalcDetail
    slack: CpaCalcDetail
    verdict: str           # human-readable conclusion
    on_critical_path: bool


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
    status: Optional[str] = None
    days_needed: int
    days_delayed: int
    effective_duration: int
    depends_on: List[CpaDependsOn]
    early_start: int
    early_finish: int
    late_start: int
    late_finish: int
    slack: int
    on_critical_path: bool
    calculation_steps: CpaCalculationSteps


class CpaFlowNode(BaseModel):
    id: str
    label: str
    display_code: str
    name: str
    milestone_display_code: str
    days_needed: int
    days_delayed: int
    effective_duration: int
    early_start: int
    early_finish: int
    late_start: int
    late_finish: int
    slack: int
    on_critical_path: bool
    status: Optional[str] = None
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
    critical_path: List[CpaCriticalPathActivity]
    activity_schedule: List[CpaActivitySchedule]
    flow_diagram: Dict[str, Any]
