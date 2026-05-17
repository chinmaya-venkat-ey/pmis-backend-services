"""UserController — HTTP adapter for /user/users/* routes (CRUD + perms-by-user + projects)."""
from __future__ import annotations

from typing import List

from app.schemas.permission import EffectivePermissionsResponse
from app.schemas.summaries import ProjectSummary, UserProjectsResponse
from app.schemas.user import (
    UserCheckLoginResponse,
    UserCreateRequest,
    UserPasswordUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services.permission_service import PermissionService
from app.services.user_service import UserService
from app.repositories.user_role_assignment_repository import UserRoleAssignmentRepository


class UserController:
    def __init__(
        self,
        user_service: UserService,
        permission_service: PermissionService,
    ):
        self.user_service = user_service
        self.permission_service = permission_service
        # Reach into the same db session as user_service for project listings.
        self.assignments = UserRoleAssignmentRepository(user_service.db)

    # ------------------------------------------------------------------ list / get

    def list_(self, *, offset, page_size, status, include_deleted, caller_vendor_id, caller_is_admin):
        rows, total = self.user_service.list_(
            offset=offset, page_size=page_size,
            status=status, include_deleted=include_deleted,
            caller_vendor_id=caller_vendor_id, caller_is_admin=caller_is_admin,
        )
        return {
            "items": [UserResponse.model_validate(r) for r in rows],
            "total": total,
            "offset": offset,
            "pageSize": page_size,
        }

    def get_details(self, user_id: str) -> UserResponse:
        return UserResponse.model_validate(self.user_service.get_by_id(user_id))

    def check_login(self, login: str) -> UserCheckLoginResponse:
        return self.user_service.check_login_available(login)

    # ------------------------------------------------------------------ create / update / delete

    def create(self, payload: UserCreateRequest, *, caller_user_id: str, caller_is_admin: bool) -> UserResponse:
        row = self.user_service.create(
            payload,
            created_by_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
        )
        return UserResponse.model_validate(row)

    def update(self, user_id: str, payload: UserUpdateRequest, *, request, caller_user_id: str, caller_is_admin: bool) -> UserResponse:
        row = self.user_service.update(
            user_id, payload,
            request=request,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return UserResponse.model_validate(row)

    def update_password(self, user_id: str, payload: UserPasswordUpdateRequest, *, caller_user_id: str) -> UserResponse:
        # Round-7 Flow 2: self-only. caller_is_admin not consulted.
        row = self.user_service.update_password(
            user_id, payload, caller_user_id=caller_user_id,
        )
        return UserResponse.model_validate(row)

    def delete(self, user_id: str, *, request, caller_user_id: str, caller_is_admin: bool) -> UserResponse:
        row = self.user_service.delete(
            user_id, request=request,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return UserResponse.model_validate(row)

    def restore(self, user_id: str, *, request, caller_user_id: str, caller_is_admin: bool) -> UserResponse:
        row = self.user_service.restore(
            user_id, request=request,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return UserResponse.model_validate(row)

    # ------------------------------------------------------------------ direct user permissions

    def list_permissions(self, user_id: str) -> EffectivePermissionsResponse:
        # 404 if user doesn't exist
        self.user_service.get_by_id(user_id)
        return self.permission_service.effective_for_user(user_id)

    def grant_permission(self, user_id: str, code: str, *, caller_user_id: str) -> EffectivePermissionsResponse:
        self.user_service.get_by_id(user_id)
        return self.permission_service.grant_to_user(user_id, code, caller_user_id=caller_user_id)

    def revoke_permission(self, user_id: str, code: str) -> EffectivePermissionsResponse:
        self.user_service.get_by_id(user_id)
        return self.permission_service.revoke_from_user(user_id, code)

    # ------------------------------------------------------------------ user → projects

    def list_projects(self, user_id: str) -> UserProjectsResponse:
        user = self.user_service.get_by_id(user_id)
        projects = self.assignments.list_projects_for_user(user_id)
        return UserProjectsResponse(
            user_id=user.id,
            user_login=user.login,
            projects=[ProjectSummary.model_validate(p) for p in projects],
        )
