"""Team management routes — serves the Manage-Team UI page.

Endpoints:
  GET  /api/v3/projects/{project_id}/team
       Full snapshot: org members, ownership, all activity assignments,
       assignable-user picker list.

  PUT  /api/v3/projects/{project_id}/team
       Bulk save: ownership + all activity assignments in one call.
       Maps directly to the UI's Submit button.

  GET  /api/v3/projects/{project_id}/ownership
       Project-level owner / approver read.

  PUT  /api/v3/projects/{project_id}/ownership
       Replace project-level owner / approver.

  GET  /api/v3/activities/{activity_id}/assignments
       Per-activity assignments (owner, owner_approver, division users/approvers).

  PUT  /api/v3/activities/{activity_id}/assignments
       Replace per-activity assignments (maps to the modal Save button).

Permission gates:
  reads  → PROJECT_MEMBERS_READ
  writes → PROJECT_MEMBERS_UPDATE
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.permissions import PROJECT_MEMBERS_READ, PROJECT_MEMBERS_UPDATE
from app.core.rbac import require_authenticated, require_permission
from app.dependencies import get_current_user_id, get_team_controller
from app.schemas.team import (
    ActivityAssignmentsRead,
    ActivityAssignmentsWrite,
    AssociatedUsersFilter,
    AssociatedUsersResponse,
    OwnershipRead,
    OwnershipWrite,
    TeamPageRequest,
    TeamPageResponse,
    TeamReadResponse,
    TeamWriteRequest,
    TeamWriteResponse,
)
from app.controllers.team_controller import TeamController

# ── project-scoped routes (/projects/{project_id}/...) ──────────────────────
project_team_router = APIRouter(prefix="/projects", tags=["team"])

# ── activity-scoped routes (/activities/{activity_id}/...) ──────────────────
activity_team_router = APIRouter(prefix="/activities", tags=["team"])

# ── top-level routes (no path-param scope) ───────────────────────────────────
associated_users_router = APIRouter(tags=["team"])


# ─────────────────────────────────────────────────────────────────────────────
# Full team snapshot
# ─────────────────────────────────────────────────────────────────────────────

@project_team_router.get(
    "/{project_id}/team",
    response_model=TeamReadResponse,
    summary="Full team snapshot for a project",
    description=(
        "Returns org-level member buckets (by role), project ownership "
        "(owner + approver), all activity assignments grouped by milestone, "
        "and the assignable-user picker list. Powers the Manage-Team page "
        "initial load."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_READ))],
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "full_team_snapshot": {
                                "summary": "Full team snapshot — project with 2 milestones, 2 activities, 2 concerned divisions",
                                "value": {
                                    "project_id": "proj-1111-2222-3333-4444",
                                    "project_name": "National Digital Identity Platform",
                                    "org_members": [
                                        {"role_id": 3, "role_name": "project_admin",  "users": [{"id": "usr-0001", "login": "rajesh.kumar",  "email": "rajesh.kumar@uidai.gov.in",  "full_name": "Rajesh Kumar"}]},
                                        {"role_id": 4, "role_name": "project_member", "users": [
                                            {"id": "usr-0002", "login": "priya.sharma",  "email": "priya.sharma@uidai.gov.in",  "full_name": "Priya Sharma"},
                                            {"id": "usr-0005", "login": "suresh.patel", "email": "suresh.patel@uidai.gov.in", "full_name": "Suresh Patel"},
                                        ]},
                                    ],
                                    "ownership": {
                                        "project_owner": [{"id": "usr-0001", "login": "rajesh.kumar", "email": "rajesh.kumar@uidai.gov.in", "full_name": "Rajesh Kumar"}],
                                        "approver":      [{"id": "usr-0002", "login": "priya.sharma", "email": "priya.sharma@uidai.gov.in", "full_name": "Priya Sharma"}],
                                    },
                                    "activities": [
                                        {
                                            "id": "act-a101", "display_code": "A1.1",
                                            "name": "Requirements Gathering",
                                            "milestone_id": "ms-m001", "milestone_name": "Planning", "milestone_display_code": "M1",
                                            "concerned_divisions": ["IT_DIV", "LEGAL_DIV"],
                                            "assignments": {
                                                "owner": [{"id": "usr-0003", "login": "amit.singh", "email": "amit.singh@uidai.gov.in", "full_name": "Amit Singh"}],
                                                "owner_approver": [{"id": "usr-0004", "login": "deepa.nair", "email": "deepa.nair@uidai.gov.in", "full_name": "Deepa Nair"}],
                                                "division_users": {
                                                    "IT_DIV":    [{"id": "usr-0001", "login": "rajesh.kumar", "email": "rajesh.kumar@uidai.gov.in", "full_name": "Rajesh Kumar"}, {"id": "usr-0002", "login": "priya.sharma", "email": "priya.sharma@uidai.gov.in", "full_name": "Priya Sharma"}],
                                                    "LEGAL_DIV": [{"id": "usr-0005", "login": "suresh.patel", "email": "suresh.patel@uidai.gov.in", "full_name": "Suresh Patel"}],
                                                },
                                                "division_approvers": {
                                                    "IT_DIV":    [{"id": "usr-0004", "login": "deepa.nair",   "email": "deepa.nair@uidai.gov.in",   "full_name": "Deepa Nair"}],
                                                    "LEGAL_DIV": [{"id": "usr-0002", "login": "priya.sharma", "email": "priya.sharma@uidai.gov.in", "full_name": "Priya Sharma"}],
                                                },
                                            },
                                        },
                                        {
                                            "id": "act-a102", "display_code": "A1.2",
                                            "name": "Architecture Design",
                                            "milestone_id": "ms-m001", "milestone_name": "Planning", "milestone_display_code": "M1",
                                            "concerned_divisions": ["IT_DIV"],
                                            "assignments": {
                                                "owner": [{"id": "usr-0003", "login": "amit.singh", "email": "amit.singh@uidai.gov.in", "full_name": "Amit Singh"}],
                                                "owner_approver": [{"id": "usr-0004", "login": "deepa.nair", "email": "deepa.nair@uidai.gov.in", "full_name": "Deepa Nair"}],
                                                "division_users":     {"IT_DIV": [{"id": "usr-0002", "login": "priya.sharma", "email": "priya.sharma@uidai.gov.in", "full_name": "Priya Sharma"}]},
                                                "division_approvers": {"IT_DIV": [{"id": "usr-0001", "login": "rajesh.kumar", "email": "rajesh.kumar@uidai.gov.in", "full_name": "Rajesh Kumar"}]},
                                            },
                                        },
                                    ],
                                    "assignable_users": [
                                        {"id": "usr-0001", "login": "rajesh.kumar",  "email": "rajesh.kumar@uidai.gov.in",  "full_name": "Rajesh Kumar"},
                                        {"id": "usr-0002", "login": "priya.sharma",  "email": "priya.sharma@uidai.gov.in",  "full_name": "Priya Sharma"},
                                        {"id": "usr-0003", "login": "amit.singh",    "email": "amit.singh@uidai.gov.in",    "full_name": "Amit Singh"},
                                        {"id": "usr-0004", "login": "deepa.nair",    "email": "deepa.nair@uidai.gov.in",    "full_name": "Deepa Nair"},
                                        {"id": "usr-0005", "login": "suresh.patel",  "email": "suresh.patel@uidai.gov.in",  "full_name": "Suresh Patel"},
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_team(
    project_id: str,
    request: Request,
    controller: Annotated[TeamController, Depends(get_team_controller)],
):
    authorization = request.headers.get("authorization") or ""
    return controller.get_team(project_id, authorization=authorization)


# ─────────────────────────────────────────────────────────────────────────────
# Bulk team save  (UI Submit button)
# ─────────────────────────────────────────────────────────────────────────────

@project_team_router.put(
    "/{project_id}/team",
    response_model=TeamWriteResponse,
    summary="Bulk save team assignments for a project",
    description=(
        "One-shot save for the entire Manage-Team page. Accepts optional "
        "ownership block and a map of activity_id → assignment payload. "
        "Each section is a full replace (previous rows for that scope are "
        "deleted before new ones are inserted). Sections omitted from the "
        "request are left unchanged."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_UPDATE))],
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "full_submit": {
                            "summary": "Submit button — ownership + 2 activities with concerned divisions",
                            "value": {
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
                            },
                        },
                        "ownership_only": {
                            "summary": "Save ownership only (no activity changes)",
                            "value": {
                                "ownership": {
                                    "project_owner": ["usr-0001"],
                                    "approver":      ["usr-0002"],
                                },
                                "activity_assignments": {},
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "success": {
                                "summary": "Both ownership and 2 activities updated",
                                "value": {
                                    "project_id": "proj-1111-2222-3333-4444",
                                    "updated_ownership": True,
                                    "updated_activities": ["act-a101", "act-a102"],
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def save_team(
    project_id: str,
    body: TeamWriteRequest,
    caller_id: Annotated[str, Depends(get_current_user_id)],
    controller: Annotated[TeamController, Depends(get_team_controller)],
):
    return controller.save_team(project_id, body, caller_id)


# ─────────────────────────────────────────────────────────────────────────────
# Project ownership
# ─────────────────────────────────────────────────────────────────────────────

@project_team_router.get(
    "/{project_id}/ownership",
    response_model=OwnershipRead,
    summary="Get project owner and approver",
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_READ))],
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "ownership_set": {
                                "summary": "Project has an owner and an approver assigned",
                                "value": {
                                    "project_owner": [{"id": "usr-0001", "login": "rajesh.kumar", "email": "rajesh.kumar@uidai.gov.in", "full_name": "Rajesh Kumar"}],
                                    "approver":      [{"id": "usr-0002", "login": "priya.sharma", "email": "priya.sharma@uidai.gov.in", "full_name": "Priya Sharma"}],
                                },
                            },
                            "ownership_empty": {
                                "summary": "No ownership assigned yet",
                                "value": {
                                    "project_owner": [],
                                    "approver":      [],
                                },
                            },
                        }
                    }
                }
            }
        }
    },
)
def get_ownership(
    project_id: str,
    controller: Annotated[TeamController, Depends(get_team_controller)],
):
    return controller.get_ownership(project_id)


@project_team_router.put(
    "/{project_id}/ownership",
    response_model=OwnershipRead,
    summary="Set project owner and approver (full replace)",
    description=(
        "Replaces all project_owner and approver assignments for the project. "
        "approver is single-select — only the first user_id in the list is stored."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_UPDATE))],
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "set_owner_and_approver": {
                            "summary": "Assign project owner and approver",
                            "value": {
                                "project_owner": ["usr-0001"],
                                "approver":      ["usr-0002"],
                            },
                        },
                        "clear_approver": {
                            "summary": "Keep owner, remove approver",
                            "value": {
                                "project_owner": ["usr-0001"],
                                "approver":      [],
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "after_save": {
                                "summary": "Ownership after save — returns full user objects",
                                "value": {
                                    "project_owner": [{"id": "usr-0001", "login": "rajesh.kumar", "email": "rajesh.kumar@uidai.gov.in", "full_name": "Rajesh Kumar"}],
                                    "approver":      [{"id": "usr-0002", "login": "priya.sharma", "email": "priya.sharma@uidai.gov.in", "full_name": "Priya Sharma"}],
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def save_ownership(
    project_id: str,
    body: OwnershipWrite,
    caller_id: Annotated[str, Depends(get_current_user_id)],
    controller: Annotated[TeamController, Depends(get_team_controller)],
):
    return controller.save_ownership(project_id, body, caller_id)


# ─────────────────────────────────────────────────────────────────────────────
# Per-activity assignments  (modal Save button)
# ─────────────────────────────────────────────────────────────────────────────

@activity_team_router.get(
    "/{activity_id}/assignments",
    response_model=ActivityAssignmentsRead,
    summary="Get team assignments for one activity",
    description=(
        "Returns owner, owner_approver, division_users, and division_approvers "
        "for the specified activity."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_READ))],
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "with_two_divisions": {
                                "summary": "Activity with IT and Legal divisions assigned",
                                "value": {
                                    "owner":         [{"id": "usr-0003", "login": "amit.singh",  "email": "amit.singh@uidai.gov.in",  "full_name": "Amit Singh"}],
                                    "owner_approver":[{"id": "usr-0004", "login": "deepa.nair",  "email": "deepa.nair@uidai.gov.in",  "full_name": "Deepa Nair"}],
                                    "division_users": {
                                        "IT_DIV":    [
                                            {"id": "usr-0001", "login": "rajesh.kumar", "email": "rajesh.kumar@uidai.gov.in", "full_name": "Rajesh Kumar"},
                                            {"id": "usr-0002", "login": "priya.sharma", "email": "priya.sharma@uidai.gov.in", "full_name": "Priya Sharma"},
                                        ],
                                        "LEGAL_DIV": [
                                            {"id": "usr-0005", "login": "suresh.patel", "email": "suresh.patel@uidai.gov.in", "full_name": "Suresh Patel"},
                                        ],
                                    },
                                    "division_approvers": {
                                        "IT_DIV":    [{"id": "usr-0004", "login": "deepa.nair",   "email": "deepa.nair@uidai.gov.in",   "full_name": "Deepa Nair"}],
                                        "LEGAL_DIV": [{"id": "usr-0002", "login": "priya.sharma", "email": "priya.sharma@uidai.gov.in", "full_name": "Priya Sharma"}],
                                    },
                                },
                            },
                            "no_assignments": {
                                "summary": "Activity not yet configured",
                                "value": {
                                    "owner": [], "owner_approver": [],
                                    "division_users": {}, "division_approvers": {},
                                },
                            },
                        }
                    }
                }
            }
        }
    },
)
def get_activity_assignments(
    activity_id: str,
    controller: Annotated[TeamController, Depends(get_team_controller)],
):
    return controller.get_activity_assignments(activity_id)


@activity_team_router.put(
    "/{activity_id}/assignments",
    response_model=ActivityAssignmentsRead,
    summary="Save team assignments for one activity (full replace)",
    description=(
        "Replaces all assignment rows for the given activity. "
        "owner_approver and each division's approver are single-select "
        "— only the first user_id in each list is stored. "
        "Maps to the activity-configuration modal Save button."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_UPDATE))],
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "with_two_divisions": {
                            "summary": "Assign owner, approver, and two concerned divisions",
                            "value": {
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
                        },
                        "owner_only": {
                            "summary": "Assign owner only — no divisions",
                            "value": {
                                "owner":          ["usr-0003"],
                                "owner_approver": ["usr-0004"],
                                "division_users": {},
                                "division_approvers": {},
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "after_save": {
                                "summary": "Activity assignments after save — full user objects returned",
                                "value": {
                                    "owner":         [{"id": "usr-0003", "login": "amit.singh",  "email": "amit.singh@uidai.gov.in",  "full_name": "Amit Singh"}],
                                    "owner_approver":[{"id": "usr-0004", "login": "deepa.nair",  "email": "deepa.nair@uidai.gov.in",  "full_name": "Deepa Nair"}],
                                    "division_users": {
                                        "IT_DIV":    [
                                            {"id": "usr-0001", "login": "rajesh.kumar", "email": "rajesh.kumar@uidai.gov.in", "full_name": "Rajesh Kumar"},
                                            {"id": "usr-0002", "login": "priya.sharma", "email": "priya.sharma@uidai.gov.in", "full_name": "Priya Sharma"},
                                        ],
                                        "LEGAL_DIV": [{"id": "usr-0005", "login": "suresh.patel", "email": "suresh.patel@uidai.gov.in", "full_name": "Suresh Patel"}],
                                    },
                                    "division_approvers": {
                                        "IT_DIV":    [{"id": "usr-0004", "login": "deepa.nair",   "email": "deepa.nair@uidai.gov.in",   "full_name": "Deepa Nair"}],
                                        "LEGAL_DIV": [{"id": "usr-0002", "login": "priya.sharma", "email": "priya.sharma@uidai.gov.in", "full_name": "Priya Sharma"}],
                                    },
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def save_activity_assignments(
    activity_id: str,
    body: ActivityAssignmentsWrite,
    caller_id: Annotated[str, Depends(get_current_user_id)],
    controller: Annotated[TeamController, Depends(get_team_controller)],
):
    return controller.save_activity_assignments(activity_id, body, caller_id)


# ─────────────────────────────────────────────────────────────────────────────
# UI-shaped team page  (prepopulate + save in one call each)
# ─────────────────────────────────────────────────────────────────────────────

@project_team_router.get(
    "/{project_id}/team-page",
    response_model=TeamPageResponse,
    summary="Prepopulate Manage-Team page (UI-shaped)",
    description=(
        "Returns the exact `state` + `userDirectory` objects the Manage-Team HTML "
        "needs — no frontend transformation required. "
        "`orgUser` rows come from user-role-assignments (read-only). "
        "`projectOwner` and `activities` reflect saved ownership and assignments."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_READ))],
)
def get_team_page(
    project_id: str,
    request: Request,
    controller: Annotated[TeamController, Depends(get_team_controller)],
):
    authorization = request.headers.get("authorization") or ""
    return controller.get_team_page(project_id, authorization=authorization)


@project_team_router.put(
    "/{project_id}/team-page",
    response_model=TeamPageResponse,
    summary="Save Manage-Team page (UI Submit button)",
    description=(
        "Accepts the `state` object verbatim from the Manage-Team HTML Submit button. "
        "`projectOwner` and `activities` are persisted directly (full replace per scope). "
        "`orgUser` is diffed against the current project role assignments; if it "
        "differs, the changed roles are forwarded to user-management via the "
        "caller's JWT. If the user-management call fails, the entire save is "
        "aborted (502 Bad Gateway) so partial state is never persisted. "
        "Returns the refreshed page state identical to GET team-page."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_UPDATE))],
)
def save_team_page(
    project_id: str,
    body: TeamPageRequest,
    request: Request,
    caller_id: Annotated[str, Depends(get_current_user_id)],
    controller: Annotated[TeamController, Depends(get_team_controller)],
):
    authorization = request.headers.get("authorization") or ""
    return controller.save_team_page(project_id, body, caller_id, authorization)


# ─────────────────────────────────────────────────────────────────────────────
# Associated users — flag-driven lookup (no path-scoped project)
# ─────────────────────────────────────────────────────────────────────────────

@associated_users_router.post(
    "/associated-users",
    response_model=AssociatedUsersResponse,
    summary="Look up users by a project's organizations, owner division, or a division id",
    description=(
        "Flag-driven lookup. Each flag turns on one match source; the "
        "response is the union of users matching any active source. Each "
        "user entry carries `matchedOrganizations`, `matchedOwnerDivision`, "
        "and `matchedDivision` so the caller can see why the user was "
        "included.\n\n"
        "Constraints:\n"
        "  • At least one details flag must be true (else 422).\n"
        "  • `orgDetails` / `ownerDetails` require `projectId` (else 422).\n"
        "  • `divisionDetails` requires `divisionId` (else 422).\n"
        "  • `projectId` must reference a live project (else 404).\n"
        "  • `divisionId` must reference a row in `masters.divisions` "
        "(else 422).\n\n"
        "Authenticated-only: data returned is filtered by the project / "
        "division references in the body, not by the caller's role."
    ),
    dependencies=[Depends(require_authenticated())],
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "all_three": {
                            "summary": "All three sources — orgs + owner division + specific division",
                            "value": {
                                "projectId": "proj-1111-2222-3333-4444",
                                "divisionId": 12,
                                "orgDetails": True,
                                "ownerDetails": True,
                                "divisionDetails": True,
                            },
                        },
                        "orgs_only": {
                            "summary": "Project organizations only",
                            "value": {
                                "projectId": "proj-1111-2222-3333-4444",
                                "orgDetails": True,
                            },
                        },
                        "owner_division_only": {
                            "summary": "Project owner division only",
                            "value": {
                                "projectId": "proj-1111-2222-3333-4444",
                                "ownerDetails": True,
                            },
                        },
                        "specific_division_only": {
                            "summary": "Specific division id only (no project context)",
                            "value": {
                                "divisionId": 12,
                                "divisionDetails": True,
                            },
                        },
                    }
                }
            }
        },
    },
)
def get_associated_users(
    body: AssociatedUsersFilter,
    controller: Annotated[TeamController, Depends(get_team_controller)],
) -> AssociatedUsersResponse:
    return controller.get_associated_users(body)
