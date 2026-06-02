"""RoleAssignmentController — HTTP adapter for role-assignment + vendor sub-listing routes."""
from __future__ import annotations

from typing import List, Union

from app.repositories.user_repository import UserRepository
from app.repositories.user_role_assignment_repository import UserRoleAssignmentRepository
from app.schemas.role_assignment import (
    ProjectRolesBulkWriteRequest,
    RoleAssignmentBatchResponse,
    RoleAssignmentCreateRequest,
    RoleAssignmentResponse,
)
from app.schemas.summaries import (
    ProjectSummary,
    UserSummary,
    VendorProjectsResponse,
)
from app.services.role_assignment_service import RoleAssignmentService


class RoleAssignmentController:
    def __init__(self, service: RoleAssignmentService):
        self.service = service
        self.assignments = UserRoleAssignmentRepository(service.db)
        self.user_repo = UserRepository(service.db)

    # ------------------------------------------------------------------ user-scoped assignments

    def list_for_user(self, user_id: str) -> List[RoleAssignmentResponse]:
        return self.service.list_for_user(user_id)

    def create_for_user(
        self,
        user_id: str,
        payload: RoleAssignmentCreateRequest,
        *,
        caller_user_id: str,
        caller_is_admin: bool,
    ) -> Union[RoleAssignmentResponse, RoleAssignmentBatchResponse]:
        return self.service.create(
            payload,
            target_user_id=user_id,
            caller_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
        )

    def delete_user_assignment(
        self,
        user_id: str,
        assignment_id: int,
        *,
        caller_user_id: str,
        caller_is_admin: bool,
    ) -> RoleAssignmentResponse:
        return self.service.delete(
            assignment_id,
            caller_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
        )

    # ------------------------------------------------------------------ project-scoped assignments

    def list_for_project(self, project_uuid: str) -> List[RoleAssignmentResponse]:
        return self.service.list_for_project(project_uuid)

    def create_for_project(
        self,
        project_uuid: str,
        payload: RoleAssignmentCreateRequest,
        *,
        caller_user_id: str,
        caller_is_admin: bool,
    ) -> Union[RoleAssignmentResponse, RoleAssignmentBatchResponse]:
        return self.service.create(
            payload,
            target_project_id=project_uuid,
            caller_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
        )

    def bulk_replace_for_project(
        self,
        project_uuid: str,
        payload: ProjectRolesBulkWriteRequest,
        *,
        caller_user_id: str,
        caller_is_admin: bool,
    ) -> List[RoleAssignmentResponse]:
        return self.service.bulk_replace_for_project(
            project_uuid,
            payload.assignments,
            caller_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
        )

    def delete_project_assignment(
        self,
        project_uuid: str,
        assignment_id: int,
        *,
        caller_user_id: str,
        caller_is_admin: bool,
    ) -> RoleAssignmentResponse:
        return self.service.delete(
            assignment_id,
            caller_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
        )

    # ------------------------------------------------------------------ vendor sub-listings

    def list_vendor_projects(self, vendor_id: str) -> VendorProjectsResponse:
        # cross-schema read of masters.vendors + project.project_vendors → project.projects
        # We don't have a vendor lookup here — but the response shape needs vendor_name.
        # Defer to a slim placeholder; if vendor doesn't exist, return empty list.
        from app.models._cross_schema import Vendor

        vendor = self.service.db.get(Vendor, vendor_id)
        projects = self.assignments.list_projects_for_vendor(vendor_id)
        return VendorProjectsResponse(
            vendor_id=vendor_id,
            vendor_name=vendor.name if vendor else "",
            projects=[ProjectSummary.model_validate(p) for p in projects],
        )

    def list_vendor_users(
        self,
        vendor_id: str,
        *,
        offset: int,
        page_size: int,
        include_deleted: bool,
    ) -> dict:
        rows = self.assignments.list_users_for_vendor(vendor_id)
        if not include_deleted:
            rows = [u for u in rows if u.deleted_at is None]
        total = len(rows)
        # 1-based offset pagination
        zero_based = max(0, offset - 1)
        page = rows[zero_based * page_size : zero_based * page_size + page_size]
        return {
            "items": [UserSummary.model_validate(u) for u in page],
            "total": total,
            "offset": offset,
            "pageSize": page_size,
        }
