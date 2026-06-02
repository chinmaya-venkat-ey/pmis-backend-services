"""UserController — HTTP adapter for /user/users/* routes (CRUD + perms-by-user + projects)."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select

from app.models._cross_schema import Division, Vendor
from app.models.role import Role
from app.models.user_role import UserRole
from app.models.user_role_assignment import UserRoleAssignment
from app.repositories.rbac_repository import RbacRepository
from app.repositories.user_role_assignment_repository import UserRoleAssignmentRepository
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


# 2026-06-02: ORG_TIER_ROLES tuple removed. _derive_org_roles now returns
# every builtin role the user holds, auto-discovered from the DB. New
# roles created via migration are recognized automatically.


class UserController:
    def __init__(
        self,
        user_service: UserService,
        permission_service: PermissionService,
    ):
        self.user_service = user_service
        self.permission_service = permission_service
        self.assignments = UserRoleAssignmentRepository(user_service.db)
        self.rbac = RbacRepository(user_service.db)

    def _is_super_admin(self, user_id: str) -> bool:
        from app.core.permissions import SUPER_ADMIN_ROLE
        role = self.rbac.get_role_by_name(SUPER_ADMIN_ROLE)
        if role is None:
            return False
        db = self.user_service.db
        if db.execute(
            select(UserRole.user_id)
            .where(UserRole.user_id == user_id)
            .where(UserRole.role_id == role.id)
            .limit(1)
        ).first():
            return True
        return db.execute(
            select(UserRoleAssignment.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(UserRoleAssignment.role_id == role.id)
            .limit(1)
        ).first() is not None

    def _derive_org_roles(self, user_id: str) -> List[str]:
        """Return every builtin role the user currently holds (legacy
        user_roles + scoped user_role_assignments combined). Auto-derived
        from the DB — new roles added via migration (with ``builtin=True``
        on the row) are picked up automatically, no Python edit needed.

        Custom (non-builtin) roles such as ``test_role`` are excluded so
        they don't pollute the user-facing tier label. The
        ``users.users.org_role`` column is no longer consulted; it stays
        as a legacy varchar hint that's set/maintained separately via
        PATCH /users/{id} but isn't surfaced in the response.

        Returns names sorted alphabetically (deterministic order without
        a priority bias). Frontend decides how to render multiple roles.
        """
        db = self.user_service.db
        legacy = set(db.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .where(Role.builtin.is_(True))
        ).scalars())
        scoped = set(db.execute(
            select(Role.name)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(Role.builtin.is_(True))
            .distinct()
        ).scalars())
        return sorted(legacy | scoped)

    def _build_user_response(self, user) -> UserResponse:
        db = self.user_service.db
        is_admin = self.rbac.user_has_admin_role(user.id)
        is_super_admin = self._is_super_admin(user.id)
        data = {
            col: getattr(user, col)
            for col in user.__class__.__table__.columns.keys()
            if hasattr(user, col)
        }
        data["is_admin"] = is_admin
        data["is_super_admin"] = is_super_admin

        # Resolve vendor_name from masters.vendors mirror.
        if data.get("vendor_id"):
            vendor = db.get(Vendor, data["vendor_id"])
            data["vendor_name"] = vendor.name if vendor else None
        else:
            data["vendor_name"] = None

        # Resolve division_label from masters.divisions mirror.
        if data.get("division"):
            div = db.execute(
                select(Division).where(Division.code == data["division"])
            ).scalar_one_or_none()
            data["division_label"] = div.label if div else None
        else:
            data["division_label"] = None

        # Derive org_role from live role assignments (Bug #16).
        # 2026-06-02: now returns the full list of builtin role names the
        # user holds — auto-discovered from the DB, no hand-maintained
        # priority tuple.
        data["org_role"] = self._derive_org_roles(user.id)

        # Convenience concat — monolith parity. Joins first + last with a
        # space; falls back to ``login`` when both names are empty. Lets
        # the FE render a user label without an "or" chain on every row.
        first = (data.get("first_name") or "").strip()
        last = (data.get("last_name") or "").strip()
        joined = " ".join(filter(None, [first, last]))
        data["full_name"] = joined or data.get("login")

        return UserResponse.model_validate(data)

    # ------------------------------------------------------------------ list / get

    def list_(self, *, offset, page_size, status, include_deleted, caller_vendor_id, caller_is_admin, caller_can_see_all=False):
        rows, total = self.user_service.list_(
            offset=offset, page_size=page_size,
            status=status, include_deleted=include_deleted,
            caller_vendor_id=caller_vendor_id, caller_is_admin=caller_is_admin,
            caller_can_see_all=caller_can_see_all,
        )
        return {
            "items": [self._build_user_response(r) for r in rows],
            "total": total,
            "offset": offset,
            "pageSize": page_size,
        }

    def get_details(self, user_id: str) -> UserResponse:
        return self._build_user_response(self.user_service.get_by_id(user_id))

    def check_login(self, login: str) -> UserCheckLoginResponse:
        return self.user_service.check_login_available(login)

    # ------------------------------------------------------------------ create / update / delete

    def create(self, payload: UserCreateRequest, *, caller_user_id: str, caller_is_admin: bool) -> UserResponse:
        row = self.user_service.create(
            payload,
            created_by_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
        )
        return self._build_user_response(row)

    def update(self, user_id: str, payload: UserUpdateRequest, *, request, caller_user_id: str, caller_is_admin: bool) -> UserResponse:
        row = self.user_service.update(
            user_id, payload,
            request=request,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self._build_user_response(row)

    def update_password(self, user_id: str, payload: UserPasswordUpdateRequest, *, caller_user_id: str) -> UserResponse:
        row = self.user_service.update_password(
            user_id, payload, caller_user_id=caller_user_id,
        )
        return self._build_user_response(row)

    def delete(self, user_id: str, *, request, caller_user_id: str, caller_is_admin: bool) -> UserResponse:
        row = self.user_service.delete(
            user_id, request=request,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self._build_user_response(row)

    def restore(self, user_id: str, *, request, caller_user_id: str, caller_is_admin: bool) -> UserResponse:
        row = self.user_service.restore(
            user_id, request=request,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self._build_user_response(row)

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
