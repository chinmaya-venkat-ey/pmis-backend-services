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

# ── Sample user chips reused across schema examples ─────────────────────────
_EX_USER1 = {"id": "usr-0001", "login": "rajesh.kumar",  "email": "rajesh.kumar@uidai.gov.in",  "first_name": "Rajesh", "last_name": "Kumar"}
_EX_USER2 = {"id": "usr-0002", "login": "priya.sharma",  "email": "priya.sharma@uidai.gov.in",  "first_name": "Priya",  "last_name": "Sharma"}
_EX_USER3 = {"id": "usr-0003", "login": "amit.singh",    "email": "amit.singh@uidai.gov.in",    "first_name": "Amit",   "last_name": "Singh"}
_EX_USER4 = {"id": "usr-0004", "login": "deepa.nair",    "email": "deepa.nair@uidai.gov.in",    "first_name": "Deepa",  "last_name": "Nair"}
_EX_USER5 = {"id": "usr-0005", "login": "suresh.patel",  "email": "suresh.patel@uidai.gov.in",  "first_name": "Suresh", "last_name": "Patel"}


# ── Shared user chip ────────────────────────────────────────────────────────

class TeamUserChip(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={"example": _EX_USER1},
    )
    id: str
    login: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


# ── Org-level role bucket (from user_role_assignments) ──────────────────────

class OrgMemberBucket(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "role_id": 3,
            "role_name": "project_admin",
            "users": [_EX_USER1, _EX_USER2],
        }
    })
    role_id: int
    role_name: str
    users: List[TeamUserChip] = Field(default_factory=list)


# ── Project ownership (project_owner / approver) ────────────────────────────

class OwnershipRead(BaseModel):
    """Wire shape returned by GET .../ownership and embedded in GET .../team."""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "project_owner": [_EX_USER1],
            "approver": [_EX_USER2],
        }
    })
    project_owner: List[TeamUserChip] = Field(default_factory=list)
    approver: List[TeamUserChip] = Field(default_factory=list)


class OwnershipWrite(BaseModel):
    """Body accepted by PUT .../ownership."""
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "project_owner": ["usr-0001"],
                "approver": ["usr-0002"],
            }
        },
    )
    project_owner: List[str] = Field(default_factory=list, description="User IDs")
    approver: List[str] = Field(default_factory=list, description="User IDs (single approver; first wins)")


# ── Per-activity assignments ─────────────────────────────────────────────────

class ActivityAssignmentsRead(BaseModel):
    """Assignments shape for one activity."""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "owner": [_EX_USER3],
            "owner_approver": [_EX_USER4],
            "division_users": {
                "IT_DIV":    [_EX_USER1, _EX_USER2],
                "LEGAL_DIV": [_EX_USER5],
            },
            "division_approvers": {
                "IT_DIV":    [_EX_USER4],
                "LEGAL_DIV": [_EX_USER2],
            },
        }
    })
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
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "owner":         ["usr-0003"],
                "owner_approver":["usr-0004"],
                "division_users": {
                    "IT_DIV":    ["usr-0001", "usr-0002"],
                    "LEGAL_DIV": ["usr-0005"],
                },
                "division_approvers": {
                    "IT_DIV":    ["usr-0004"],
                    "LEGAL_DIV": ["usr-0002"],
                },
            }
        },
    )
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
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": "act-a101",
            "display_code": "A1.1",
            "name": "Requirements Gathering",
            "milestone_id": "ms-m001",
            "milestone_name": "Planning",
            "milestone_display_code": "M1",
            "concerned_divisions": ["IT_DIV", "LEGAL_DIV"],
            "assignments": {
                "owner": [_EX_USER3],
                "owner_approver": [_EX_USER4],
                "division_users": {"IT_DIV": [_EX_USER1, _EX_USER2], "LEGAL_DIV": [_EX_USER5]},
                "division_approvers": {"IT_DIV": [_EX_USER4], "LEGAL_DIV": [_EX_USER2]},
            },
        }
    })
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
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "project_id": "proj-1111-2222-3333-4444",
            "project_name": "National Digital Identity Platform",
            "org_members": [
                {"role_id": 3, "role_name": "project_admin",  "users": [_EX_USER1]},
                {"role_id": 4, "role_name": "project_member", "users": [_EX_USER2, _EX_USER5]},
            ],
            "ownership": {
                "project_owner": [_EX_USER1],
                "approver":      [_EX_USER2],
            },
            "activities": [
                {
                    "id": "act-a101", "display_code": "A1.1",
                    "name": "Requirements Gathering",
                    "milestone_id": "ms-m001", "milestone_name": "Planning",
                    "milestone_display_code": "M1",
                    "concerned_divisions": ["IT_DIV", "LEGAL_DIV"],
                    "assignments": {
                        "owner": [_EX_USER3],
                        "owner_approver": [_EX_USER4],
                        "division_users": {"IT_DIV": [_EX_USER1, _EX_USER2], "LEGAL_DIV": [_EX_USER5]},
                        "division_approvers": {"IT_DIV": [_EX_USER4], "LEGAL_DIV": [_EX_USER2]},
                    },
                },
                {
                    "id": "act-a102", "display_code": "A1.2",
                    "name": "Architecture Design",
                    "milestone_id": "ms-m001", "milestone_name": "Planning",
                    "milestone_display_code": "M1",
                    "concerned_divisions": ["IT_DIV"],
                    "assignments": {
                        "owner": [_EX_USER3],
                        "owner_approver": [_EX_USER4],
                        "division_users": {"IT_DIV": [_EX_USER2]},
                        "division_approvers": {"IT_DIV": [_EX_USER1]},
                    },
                },
            ],
            "assignable_users": [_EX_USER1, _EX_USER2, _EX_USER3, _EX_USER4, _EX_USER5],
        }
    })
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
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "ownership": {
                    "project_owner": ["usr-0001"],
                    "approver":      ["usr-0002"],
                },
                "activity_assignments": {
                    "act-a101": {
                        "owner":          ["usr-0003"],
                        "owner_approver": ["usr-0004"],
                        "division_users": {
                            "IT_DIV":    ["usr-0001", "usr-0002"],
                            "LEGAL_DIV": ["usr-0005"],
                        },
                        "division_approvers": {
                            "IT_DIV":    ["usr-0004"],
                            "LEGAL_DIV": ["usr-0002"],
                        },
                    },
                    "act-a102": {
                        "owner":          ["usr-0003"],
                        "owner_approver": ["usr-0004"],
                        "division_users":     {"IT_DIV": ["usr-0002"]},
                        "division_approvers": {"IT_DIV": ["usr-0001"]},
                    },
                },
            }
        },
    )
    ownership: Optional[OwnershipWrite] = None
    activity_assignments: Dict[str, ActivityAssignmentEntry] = Field(
        default_factory=dict,
        description="activity_id → assignment payload",
    )


class TeamWriteResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "project_id": "proj-1111-2222-3333-4444",
            "updated_ownership": True,
            "updated_activities": ["act-a101", "act-a102"],
        }
    })
    project_id: str
    updated_ownership: bool
    updated_activities: List[str] = Field(default_factory=list, description="activity IDs updated")
