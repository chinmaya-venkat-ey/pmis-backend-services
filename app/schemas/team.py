"""Pydantic schemas for the Manage-Team APIs.

Endpoints served:
  GET  /api/v3/projects/{id}/team                  — full team read
  PUT  /api/v3/projects/{id}/team                  — bulk team submit
  GET  /api/v3/projects/{id}/ownership             — project owner/approver read
  PUT  /api/v3/projects/{id}/ownership             — set project owner/approver
  GET  /api/v3/activities/{id}/assignments         — per-activity assignments read
  PUT  /api/v3/activities/{id}/assignments         — per-activity assignments write
  GET  /api/v3/projects/{id}/team-page             — UI-shaped snapshot (Manage Team page load)
  PUT  /api/v3/projects/{id}/team-page             — UI-shaped bulk save (Submit button)
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# ── Shared description strings (avoid duplication across Field() calls) ─────
_DESC_USER_IDS = "User IDs"
_DESC_USER_IDS_APPROVER = "User IDs (single approver; first wins)"
_EX_ACTIVITY_NAME = "Requirements Gathering"


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
    project_owner: List[str] = Field(default_factory=list, description=_DESC_USER_IDS)
    approver: List[str] = Field(default_factory=list, description=_DESC_USER_IDS_APPROVER)


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
    owner: List[str] = Field(default_factory=list, description=_DESC_USER_IDS)
    owner_approver: List[str] = Field(
        default_factory=list, description=_DESC_USER_IDS_APPROVER
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
            "name": _EX_ACTIVITY_NAME,
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
                    "name": _EX_ACTIVITY_NAME,
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
    project_code: Optional[str] = None
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
            "project_code": "UIDAI-PR260525124245137",
            "updated_ownership": True,
            "updated_activities": ["act-a101", "act-a102"],
        }
    })
    project_id: str
    project_code: Optional[str] = None
    updated_ownership: bool
    updated_activities: List[str] = Field(default_factory=list, description="activity IDs updated")


# ─────────────────────────────────────────────────────────────────────────────
# UI-shaped schemas for GET/PUT /projects/{id}/team-page
#
# These mirror the JS `state` + `USER_DIRECTORY` objects in Manage Team.html
# exactly so the frontend can use the response with no transformation.
#
# Wire keys are camelCase (alias_generator=to_camel).
# ─────────────────────────────────────────────────────────────────────────────

class UserDirectoryEntry(BaseModel):
    """One entry in the userDirectory array: { id, name } — same shape as
    USER_DIRECTORY in the HTML. `name` is formatted as 'First Last (login)'."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
    id: str
    name: str


class OrgUserRow(BaseModel):
    """One row of state.orgUser: { roleLabel, users: [id, ...] }.
    Read-only from the UI; orgUser changes are managed by user-management."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )
    role_label: str
    users: List[str] = Field(default_factory=list, description=_DESC_USER_IDS)


class ProjectOwnerRow(BaseModel):
    """One row of state.projectOwner: { roleLabel, users, single? }.
    single=true marks the Approver row (single-select in UI)."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )
    role_label: str
    users: List[str] = Field(default_factory=list, description=_DESC_USER_IDS)
    single: bool = False


class TeamPageActivity(BaseModel):
    """One entry of state.activities — mirrors the JS activity object exactly."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )
    id: str
    display_code: str = Field(description="Activity display code, e.g. 'A1.1' (wire: displayCode)")
    name: str
    milestone_id: str = Field(description="Milestone UUID (wire: milestoneId)")
    milestone_display_code: str = Field(description="Milestone display code, e.g. 'M1' (wire: milestoneDisplayCode)")
    milestone: str = Field(description="Milestone name (not ID)")
    concerned_divisions: List[str] = Field(default_factory=list)
    owner: List[str] = Field(default_factory=list, description=_DESC_USER_IDS)
    owner_approver: List[str] = Field(
        default_factory=list, description=_DESC_USER_IDS_APPROVER
    )
    division_users: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="division_code → user IDs",
    )
    division_approvers: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="division_code → approver user IDs (single; first wins)",
    )


class TeamPageResponse(BaseModel):
    """GET /projects/{id}/team-page response — the full UI state + userDirectory.

    Drop this directly into the Manage Team page: assign `projectId` / `projectName`
    to the context banner, replace `USER_DIRECTORY` with `userDirectory`, and
    set the JS `state` object to `{ orgUser, projectOwner, activities }`.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "projectId": "proj-1111-2222-3333-4444",
                "projectName": "Aadhaar Service Onboarding",
                "userDirectory": [
                    {"id": "usr-0001", "name": "Rajesh Kumar (rajesh.kumar)"},
                    {"id": "usr-0002", "name": "Priya Sharma (priya.sharma)"},
                ],
                "orgUser": [
                    {"roleLabel": "project_admin",  "users": ["usr-0001"]},
                    {"roleLabel": "project_member", "users": ["usr-0002"]},
                ],
                "projectOwner": [
                    {"roleLabel": "Approver",      "users": ["usr-0002"], "single": True},
                    {"roleLabel": "Project Owner", "users": ["usr-0001"]},
                ],
                "activities": [
                    {
                        "id": "act-a101",
                        "name": _EX_ACTIVITY_NAME,
                        "milestone": "Planning",
                        "concernedDivisions": ["IT_DIV", "LEGAL_DIV"],
                        "owner": ["usr-0001"],
                        "ownerApprover": ["usr-0002"],
                        "divisionUsers": {"IT_DIV": ["usr-0001"], "LEGAL_DIV": ["usr-0002"]},
                        "divisionApprovers": {"IT_DIV": ["usr-0002"], "LEGAL_DIV": ["usr-0001"]},
                    }
                ],
            }
        },
    )
    project_id: str
    project_code: Optional[str] = None
    project_name: str
    owner_division: Optional["DivisionRef"] = Field(
        default=None,
        description="Project's owner division resolved against masters.divisions. "
                    "None when the project has no owner division set.",
    )
    concerned_divisions: List["DivisionRef"] = Field(
        default_factory=list,
        description="Union of concerned_divisions across all live activities, "
                    "resolved against masters.divisions and sorted by code.",
    )
    user_directory: List[UserDirectoryEntry] = Field(default_factory=list)
    org_user: List[OrgUserRow] = Field(default_factory=list)
    project_owner: List[ProjectOwnerRow] = Field(default_factory=list)
    activities: List[TeamPageActivity] = Field(default_factory=list)


class TeamPageRequest(BaseModel):
    """PUT /projects/{id}/team-page body — the JS `state` object verbatim.

    All three sections are now writable:
      - ``orgUser`` is diffed against current state; changed roles are
        forwarded to user-management's bulk-replace role-assignment
        endpoint over HTTP, carrying the caller's JWT.
      - ``projectOwner`` is persisted to project.project_ownership (full
        replace per project).
      - ``activities`` is persisted to project.activity_assignment (full
        replace per activity).

    If the user-management call fails, the whole save is aborted (502
    Bad Gateway) before any local writes — no partial cross-schema state.
    Send ``orgUser: []`` (or omit it) to skip the cross-service call.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )
    org_user: List[OrgUserRow] = Field(
        default_factory=list,
        description="Diffed against current org-user assignments; changed "
                    "roles are forwarded to user-management. Empty list "
                    "skips the cross-service call.",
    )
    project_owner: List[ProjectOwnerRow] = Field(default_factory=list)
    activities: List[TeamPageActivity] = Field(default_factory=list)


# ── Shared masters references ───────────────────────────────────────────────

class VendorRef(BaseModel):
    """Vendor (organization) id + name, hydrated from masters.vendors."""
    model_config = ConfigDict(json_schema_extra={
        "example": {"id": "ven-aaaa-1111", "name": "Tata Consultancy Services"}
    })
    id: str
    name: Optional[str] = None


class DivisionRef(BaseModel):
    """Division id + code + name, hydrated from masters.divisions.

    `id` and `name` are null when the code does not resolve to a row in
    masters.divisions (e.g. legacy 'others' or stale codes). `code` is
    always populated.
    """
    model_config = ConfigDict(json_schema_extra={
        "example": {"id": 12, "code": "IT_DIV", "name": "Information Technology"}
    })
    id: Optional[int] = None
    code: str
    name: Optional[str] = None


# ── Associated-users (POST /associated-users) ───────────────────────────────

class AssociatedUsersFilter(BaseModel):
    """Body for POST /associated-users.

    Flag-driven lookup. At least one details flag must be true.

      - orgDetails (requires projectId):
            return users whose users.vendor_id is in this project's
            project_vendors. Each matching user carries the matched
            organization in `matchedOrganizations`.
      - ownerDetails (requires projectId):
            return users whose users.division equals the project's owner
            division (projects.owner). Each matching user carries the
            owner division in `matchedOwnerDivision`.
      - divisionDetails (requires divisionId):
            return users whose users.division equals the code of the
            division row identified by `divisionId`. Each matching user
            carries that division in `matchedDivision`.

    Multiple flags can be true; the response is the union. A single user
    may have multiple `matched*` lists populated if they match multiple
    sources.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        json_schema_extra={
            "example": {
                "projectId": "proj-1111-2222-3333-4444",
                "divisionId": 12,
                "orgDetails": True,
                "ownerDetails": True,
                "divisionDetails": True,
            }
        },
    )
    project_id: Optional[str] = Field(
        default=None,
        description="Project UUID. Required when orgDetails or ownerDetails is true.",
    )
    division_id: Optional[int] = Field(
        default=None,
        description="masters.divisions.id (integer). Required when divisionDetails is true.",
    )
    org_details: bool = False
    owner_details: bool = False
    division_details: bool = False


class AssociatedUserEntry(BaseModel):
    """One user in the union, with the match buckets that included them.

    Each `matched*` list is populated only when the corresponding details
    flag in the request was true AND this user's record matched that source.
    Lists are empty otherwise.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "id": "usr-0001",
                "login": "rajesh.kumar",
                "email": "rajesh.kumar@uidai.gov.in",
                "firstName": "Rajesh",
                "lastName": "Kumar",
                "matchedOrganizations": [
                    {"id": "ven-aaaa-1111", "name": "Tata Consultancy Services"},
                ],
                "matchedOwnerDivision": [
                    {"id": 12, "code": "IT_DIV", "name": "Information Technology"},
                ],
                "matchedDivision": [],
            }
        },
    )
    id: str
    login: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    matched_organizations: List[VendorRef] = Field(default_factory=list)
    matched_owner_division: List[DivisionRef] = Field(default_factory=list)
    matched_division: List[DivisionRef] = Field(default_factory=list)


class AssociatedUsersResponse(BaseModel):
    """Response for POST /associated-users."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "users": [
                    {
                        "id": "usr-0001", "login": "rajesh.kumar",
                        "email": "rajesh.kumar@uidai.gov.in",
                        "firstName": "Rajesh", "lastName": "Kumar",
                        "matchedOrganizations": [
                            {"id": "ven-aaaa-1111", "name": "Tata Consultancy Services"},
                        ],
                        "matchedOwnerDivision": [
                            {"id": 12, "code": "IT_DIV", "name": "Information Technology"},
                        ],
                        "matchedDivision": [],
                    }
                ]
            }
        },
    )
    users: List[AssociatedUserEntry] = Field(default_factory=list)
