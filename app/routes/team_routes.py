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

from fastapi import APIRouter, Depends

from app.core.permissions import PROJECT_MEMBERS_READ, PROJECT_MEMBERS_UPDATE
from app.core.rbac import require_permission
from app.dependencies import get_current_user_id, get_team_controller
from app.schemas.team import (
    ActivityAssignmentsRead,
    ActivityAssignmentsWrite,
    OwnershipRead,
    OwnershipWrite,
    TeamReadResponse,
    TeamWriteRequest,
    TeamWriteResponse,
)
from app.controllers.team_controller import TeamController

# ── project-scoped routes (/projects/{project_id}/...) ──────────────────────
project_team_router = APIRouter(prefix="/projects", tags=["team"])

# ── activity-scoped routes (/activities/{activity_id}/...) ──────────────────
activity_team_router = APIRouter(prefix="/activities", tags=["team"])


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
)
def get_team(
    project_id: str,
    controller: TeamController = Depends(get_team_controller),
):
    return controller.get_team(project_id)


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
)
def save_team(
    project_id: str,
    body: TeamWriteRequest,
    caller_id: str = Depends(get_current_user_id),
    controller: TeamController = Depends(get_team_controller),
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
)
def get_ownership(
    project_id: str,
    controller: TeamController = Depends(get_team_controller),
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
)
def save_ownership(
    project_id: str,
    body: OwnershipWrite,
    caller_id: str = Depends(get_current_user_id),
    controller: TeamController = Depends(get_team_controller),
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
)
def get_activity_assignments(
    activity_id: str,
    controller: TeamController = Depends(get_team_controller),
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
)
def save_activity_assignments(
    activity_id: str,
    body: ActivityAssignmentsWrite,
    caller_id: str = Depends(get_current_user_id),
    controller: TeamController = Depends(get_team_controller),
):
    return controller.save_activity_assignments(activity_id, body, caller_id)
