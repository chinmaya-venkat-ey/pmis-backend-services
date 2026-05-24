"""Pydantic schemas for the Manage-Team APIs.

Endpoints served:
  GET  /api/v3/projects/{id}/team                  — full team read
  PUT  /api/v3/projects/{id}/team                  — bulk team submit
  GET  /api/v3/projects/{id}/ownership             — project owner/approver read
  PUT  /api/v3/projects/{id}/ownership             — set project owner/approver
  GET  /api/v3/activities/{id}/assignments         — per-activity assignments read
  PUT  /api/v3/activities/{id}/assignments         — per-activity assignments write
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Shared user chip ────────────────────────────────────────────────────────

class TeamUserChip(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    login: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


# ── Org-level role bucket (from user_role_assignments) ──────────────────────

class OrgMemberBucket(BaseModel):
    role_id: int
    role_name: str
    users: List[TeamUserChip] = Field(default_factory=list)


# ── Project ownership (project_owner / approver) ────────────────────────────

class OwnershipRead(BaseModel):
    """Wire shape returned by GET .../ownership and embedded in GET .../team."""
    project_owner: List[TeamUserChip] = Field(default_factory=list)
    approver: List[TeamUserChip] = Field(default_factory=list)


class OwnershipWrite(BaseModel):
    """Body accepted by PUT .../ownership."""
    model_config = ConfigDict(extra="ignore")
    project_owner: List[str] = Field(default_factory=list, description="User IDs")
    approver: List[str] = Field(default_factory=list, description="User IDs (single approver; first wins)")


# ── Per-activity assignments ─────────────────────────────────────────────────

class ActivityAssignmentsRead(BaseModel):
    """Assignments shape for one activity."""
    owner: List[TeamUserChip] = Field(default_factory=list)
    owner_approver: List[TeamUserChip] = Field(default_factory=list)
    division_users: Dict[str, List[TeamUserChip]] = Field(
        default_factory=dict,
        description="division_code → list of assigned users",
    )
    division_approvers: Dict[str, List[TeamUserChip]] = Field(
        default_factory=dict,
        description="division_code → single approver (list for consistency)",
    )


class ActivityAssignmentsWrite(BaseModel):
    """Body accepted by PUT .../assignments."""
    model_config = ConfigDict(extra="ignore")
    owner: List[str] = Field(default_factory=list, description="User IDs")
    owner_approver: List[str] = Field(
        default_factory=list, description="User IDs (single approver; first wins)"
    )
    division_users: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="division_code → list of user IDs",
    )
    division_approvers: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="division_code → list of user IDs (single approver; first wins)",
    )


# ── Activity summary row embedded in GET .../team ───────────────────────────

class TeamActivityRow(BaseModel):
    id: str
    display_code: str
    name: str
    milestone_id: str
    milestone_name: str
    milestone_display_code: str
    concerned_divisions: List[str] = Field(default_factory=list)
    assignments: ActivityAssignmentsRead


# ── Full-team read response ──────────────────────────────────────────────────

class TeamReadResponse(BaseModel):
    project_id: str
    project_name: str
    org_members: List[OrgMemberBucket] = Field(default_factory=list)
    ownership: OwnershipRead
    activities: List[TeamActivityRow] = Field(default_factory=list)
    assignable_users: List[TeamUserChip] = Field(default_factory=list)


# ── Bulk team write body ─────────────────────────────────────────────────────

class ActivityAssignmentEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    owner: List[str] = Field(default_factory=list)
    owner_approver: List[str] = Field(default_factory=list)
    division_users: Dict[str, List[str]] = Field(default_factory=dict)
    division_approvers: Dict[str, List[str]] = Field(default_factory=dict)


class TeamWriteRequest(BaseModel):
    """Body for PUT /projects/{id}/team (one-shot bulk save)."""
    model_config = ConfigDict(extra="ignore")
    ownership: Optional[OwnershipWrite] = None
    activity_assignments: Dict[str, ActivityAssignmentEntry] = Field(
        default_factory=dict,
        description="activity_id → assignment payload",
    )


class TeamWriteResponse(BaseModel):
    project_id: str
    updated_ownership: bool
    updated_activities: List[str] = Field(default_factory=list, description="activity IDs updated")
