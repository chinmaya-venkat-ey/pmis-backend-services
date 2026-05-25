"""Routes for /user/users/{id}/role-assignments/*, /user/projects/{uuid}/role-assignments/*,
and /user/vendors/{vid}/{projects,users}/list (vendor sub-listings).
"""
from __future__ import annotations

from typing import List, Union

from fastapi import APIRouter, Depends, Query, status

from app.controllers.role_assignment_controller import RoleAssignmentController
from app.core.permissions import (
    PROJECT_MEMBERS_READ,
    PROJECT_MEMBERS_UPDATE,
    PROJECTS_READ_ALL,
    RBAC_ASSIGN,
    USERS_READ_ALL,
)
from app.core.rbac import require_any_permission, require_authenticated, require_permission
from app.dependencies import (
    get_caller_is_admin,
    get_current_user_id,
    get_role_assignment_controller,
)
from app.schemas.role_assignment import (
    ProjectRolesBulkWriteRequest,
    RoleAssignmentBatchResponse,
    RoleAssignmentCreateRequest,
    RoleAssignmentResponse,
)
from app.schemas.summaries import VendorProjectsResponse


# -- User-scoped role-assignments (mounted under /user/users) ---------------

user_assignments_router = APIRouter(prefix="/users", tags=["role_assignments"])


@user_assignments_router.get(
    "/{user_id}/role-assignments",
    response_model=List[RoleAssignmentResponse],
    summary="List a user's role assignments",
    dependencies=[Depends(require_authenticated())],
)
def list_user_role_assignments(
    user_id: str,
    controller: Annotated[RoleAssignmentController, Depends(get_role_assignment_controller)] = Depends(get_role_assignment_controller),
):
    return controller.list_for_user(user_id)


@user_assignments_router.post(
    "/{user_id}/role-assignments",
    response_model=Union[RoleAssignmentResponse, RoleAssignmentBatchResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Grant a role to a user (global / org / project scope, or batch project_ids)",
    dependencies=[Depends(require_permission(RBAC_ASSIGN))],
    responses={
        403: {"description": "Caller cannot grant this role at this scope"},
        404: {"description": "User or role not found"},
    },
)
def create_user_role_assignment(
    user_id: str,
    payload: RoleAssignmentCreateRequest,
    controller: Annotated[RoleAssignmentController, Depends(get_role_assignment_controller)] = Depends(get_role_assignment_controller),
    caller_user_id: Annotated[str, Depends(get_current_user_id)] = Depends(get_current_user_id),
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)] = Depends(get_caller_is_admin),
):
    return controller.create_for_user(
        user_id, payload,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@user_assignments_router.delete(
    "/{user_id}/role-assignments/{assignment_id}",
    response_model=RoleAssignmentResponse,
    summary="Revoke a role assignment",
    dependencies=[Depends(require_permission(RBAC_ASSIGN))],
)
def delete_user_role_assignment(
    user_id: str,
    assignment_id: int,
    controller: Annotated[RoleAssignmentController, Depends(get_role_assignment_controller)] = Depends(get_role_assignment_controller),
    caller_user_id: Annotated[str, Depends(get_current_user_id)] = Depends(get_current_user_id),
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)] = Depends(get_caller_is_admin),
):
    return controller.delete_user_assignment(
        user_id, assignment_id,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


# -- Project-scoped role-assignments (mounted under /user/projects) --------

project_assignments_router = APIRouter(prefix="/projects", tags=["role_assignments"])


@project_assignments_router.get(
    "/{project_uuid}/role-assignments",
    response_model=List[RoleAssignmentResponse],
    summary="List all role assignments on a project",
    description=(
        "Returns every user_role_assignment row scoped to this project. "
        "Powers the Organisation User section of the Manage-Team page — "
        "filter by role_name ('project_admin' / 'project_member') on the FE."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_READ))],
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "two_admins_three_members": {
                                "summary": "1 project_admin and 2 project_members assigned",
                                "value": [
                                    {
                                        "id": 101,
                                        "user_id":    "usr-0001",
                                        "user_login": "rajesh.kumar",
                                        "user_email": "rajesh.kumar@uidai.gov.in",
                                        "role_id":   3,
                                        "role_name": "project_admin",
                                        "organization_id": None,
                                        "project_id": "proj-1111-2222-3333-4444",
                                        "scope": "project",
                                        "created_at": "2026-05-01T09:00:00Z",
                                        "created_by": "admin",
                                    },
                                    {
                                        "id": 102,
                                        "user_id":    "usr-0002",
                                        "user_login": "priya.sharma",
                                        "user_email": "priya.sharma@uidai.gov.in",
                                        "role_id":   4,
                                        "role_name": "project_member",
                                        "organization_id": None,
                                        "project_id": "proj-1111-2222-3333-4444",
                                        "scope": "project",
                                        "created_at": "2026-05-01T09:05:00Z",
                                        "created_by": "admin",
                                    },
                                    {
                                        "id": 103,
                                        "user_id":    "usr-0005",
                                        "user_login": "suresh.patel",
                                        "user_email": "suresh.patel@uidai.gov.in",
                                        "role_id":   4,
                                        "role_name": "project_member",
                                        "organization_id": None,
                                        "project_id": "proj-1111-2222-3333-4444",
                                        "scope": "project",
                                        "created_at": "2026-05-01T09:10:00Z",
                                        "created_by": "admin",
                                    },
                                ],
                            },
                            "empty": {
                                "summary": "No users assigned to this project yet",
                                "value": [],
                            },
                        }
                    }
                }
            }
        }
    },
)
def list_project_role_assignments(
    project_uuid: str,
    controller: Annotated[RoleAssignmentController, Depends(get_role_assignment_controller)] = Depends(get_role_assignment_controller),
):
    return controller.list_for_project(project_uuid)


@project_assignments_router.post(
    "/{project_uuid}/role-assignments",
    response_model=Union[RoleAssignmentResponse, RoleAssignmentBatchResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Grant a project-scoped role to a user",
    dependencies=[Depends(require_permission(RBAC_ASSIGN))],
)
def create_project_role_assignment(
    project_uuid: str,
    payload: RoleAssignmentCreateRequest,
    controller: Annotated[RoleAssignmentController, Depends(get_role_assignment_controller)] = Depends(get_role_assignment_controller),
    caller_user_id: Annotated[str, Depends(get_current_user_id)] = Depends(get_current_user_id),
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)] = Depends(get_caller_is_admin),
):
    return controller.create_for_project(
        project_uuid, payload,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@project_assignments_router.put(
    "/{project_uuid}/role-assignments",
    response_model=List[RoleAssignmentResponse],
    summary="Bulk-replace project role assignments (Manage-Team Submit)",
    description=(
        "Full replace for the role names listed in the request body. "
        "For each role, all existing assignments are deleted and replaced "
        "with the supplied user list. Roles not mentioned are unchanged. "
        "Accepts role_name strings (e.g. 'project_admin', 'project_member'). "
        "Unknown user IDs are silently skipped. "
        "Returns the updated full assignment list for the project. "
        "This is the Organisation User section of the Manage-Team Submit button."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_UPDATE))],
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "org_user_submit": {
                            "summary": "Organisation User section — 1 admin, 2 members",
                            "value": {
                                "assignments": {
                                    "project_admin":  ["usr-0001"],
                                    "project_member": ["usr-0002", "usr-0005"],
                                }
                            },
                        },
                        "clear_members": {
                            "summary": "Remove all members, keep admin",
                            "value": {
                                "assignments": {
                                    "project_admin":  ["usr-0001"],
                                    "project_member": [],
                                }
                            },
                        },
                        "both_empty": {
                            "summary": "Clear all org user assignments",
                            "value": {
                                "assignments": {
                                    "project_admin":  [],
                                    "project_member": [],
                                }
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
                            "after_bulk_replace": {
                                "summary": "Updated assignment list after save",
                                "value": [
                                    {
                                        "id": 201,
                                        "user_id":    "usr-0001",
                                        "user_login": "rajesh.kumar",
                                        "user_email": "rajesh.kumar@uidai.gov.in",
                                        "role_id":   3,
                                        "role_name": "project_admin",
                                        "organization_id": None,
                                        "project_id": "proj-1111-2222-3333-4444",
                                        "scope": "project",
                                        "created_at": "2026-05-25T10:30:00Z",
                                        "created_by": "admin",
                                    },
                                    {
                                        "id": 202,
                                        "user_id":    "usr-0002",
                                        "user_login": "priya.sharma",
                                        "user_email": "priya.sharma@uidai.gov.in",
                                        "role_id":   4,
                                        "role_name": "project_member",
                                        "organization_id": None,
                                        "project_id": "proj-1111-2222-3333-4444",
                                        "scope": "project",
                                        "created_at": "2026-05-25T10:30:00Z",
                                        "created_by": "admin",
                                    },
                                    {
                                        "id": 203,
                                        "user_id":    "usr-0005",
                                        "user_login": "suresh.patel",
                                        "user_email": "suresh.patel@uidai.gov.in",
                                        "role_id":   4,
                                        "role_name": "project_member",
                                        "organization_id": None,
                                        "project_id": "proj-1111-2222-3333-4444",
                                        "scope": "project",
                                        "created_at": "2026-05-25T10:30:00Z",
                                        "created_by": "admin",
                                    },
                                ],
                            }
                        }
                    }
                }
            }
        },
    },
)
def bulk_replace_project_role_assignments(
    project_uuid: str,
    payload: ProjectRolesBulkWriteRequest,
    controller: Annotated[RoleAssignmentController, Depends(get_role_assignment_controller)] = Depends(get_role_assignment_controller),
    caller_user_id: Annotated[str, Depends(get_current_user_id)] = Depends(get_current_user_id),
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)] = Depends(get_caller_is_admin),
):
    return controller.bulk_replace_for_project(
        project_uuid, payload,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@project_assignments_router.delete(
    "/{project_uuid}/role-assignments/{assignment_id}",
    response_model=RoleAssignmentResponse,
    summary="Revoke a project-scoped role assignment",
    dependencies=[Depends(require_permission(RBAC_ASSIGN))],
)
def delete_project_role_assignment(
    project_uuid: str,
    assignment_id: int,
    controller: Annotated[RoleAssignmentController, Depends(get_role_assignment_controller)] = Depends(get_role_assignment_controller),
    caller_user_id: Annotated[str, Depends(get_current_user_id)] = Depends(get_current_user_id),
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)] = Depends(get_caller_is_admin),
):
    return controller.delete_project_assignment(
        project_uuid, assignment_id,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


# -- Vendor sub-listings (mounted under /user/vendors) ---------------------

vendor_listing_router = APIRouter(prefix="/vendors", tags=["vendor_listings"])


@vendor_listing_router.get(
    "/{vendor_id}/projects",
    response_model=VendorProjectsResponse,
    summary="List projects a vendor is mapped to (cross-schema)",
    dependencies=[Depends(require_any_permission(PROJECTS_READ_ALL))],
)
def list_vendor_projects(
    vendor_id: str,
    controller: Annotated[RoleAssignmentController, Depends(get_role_assignment_controller)] = Depends(get_role_assignment_controller),
):
    return controller.list_vendor_projects(vendor_id)


@vendor_listing_router.get(
    "/{vendor_id}/users",
    summary="List users mapped to a vendor (by direct vendor_id OR org-scoped assignment)",
    dependencies=[Depends(require_permission(USERS_READ_ALL))],
)
def list_vendor_users(
    vendor_id: str,
    offset: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_deleted: bool = Query(False),
    controller: Annotated[RoleAssignmentController, Depends(get_role_assignment_controller)] = Depends(get_role_assignment_controller),
):
    return controller.list_vendor_users(
        vendor_id,
        offset=offset, page_size=page_size,
        include_deleted=include_deleted,
    )
