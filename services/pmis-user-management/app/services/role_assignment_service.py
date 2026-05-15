"""RoleAssignmentService — Doc-41 scoped grants + Doc-42b caller-can-grant gates.

Caller-can-grant rules (simplified for first port — refine in follow-up):
  - super_admin: can grant any role at any scope
  - admin: can grant any role except super_admin, at any scope
  - org_admin: can grant project_admin / project_member / division_member on
    projects belonging to their own vendor only
  - project_admin: can grant project_member on projects they themselves are
    assigned to
  - others: cannot grant
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.errors import (
    CallerCannotGrantRoleError,
    NotFoundError,
    UserNotFoundError,
)
from app.core.permissions import (
    ADMIN_ROLE,
    ORG_ADMIN_ROLE,
    PROJECT_ADMIN_ROLE,
    PROJECT_MEMBER_ROLE,
    SUPER_ADMIN_ROLE,
)
from app.models.user import User
from app.models.user_role_assignment import UserRoleAssignment
from app.repositories.rbac_repository import RbacRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_role_assignment_repository import UserRoleAssignmentRepository
from app.schemas.role_assignment import (
    RoleAssignmentBatchResponse,
    RoleAssignmentCreateRequest,
    RoleAssignmentResponse,
)


class RoleAssignmentNotFoundError(NotFoundError):
    default_code = "ROLE_ASSIGNMENT_NOT_FOUND"


class RoleAssignmentService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRoleAssignmentRepository(db)
        self.rbac = RbacRepository(db)
        self.user_repo = UserRepository(db)

    # ------------------------------------------------------------------ reads

    def list_for_user(self, user_id: str) -> List[RoleAssignmentResponse]:
        rows = self.repo.list_by_user(user_id)
        return [self._to_response(a, role=r, user=None) for a, r in rows]

    def list_for_project(self, project_id: str) -> List[RoleAssignmentResponse]:
        rows = self.repo.list_by_project(project_id)
        return [self._to_response(a, role=r, user=u) for a, r, u in rows]

    # ------------------------------------------------------------------ create

    def create(
        self,
        payload: RoleAssignmentCreateRequest,
        *,
        target_user_id: Optional[str] = None,
        target_project_id: Optional[str] = None,
        caller_user_id: str,
        caller_is_admin: bool,
    ):
        """Returns RoleAssignmentResponse for single create, or
        RoleAssignmentBatchResponse for batch (project_ids[] case).
        """
        # Resolve target_user_id from path or body.
        user_id = target_user_id or payload.user_id
        if not user_id:
            raise UserNotFoundError("user_id is required (path or body)")
        if self.user_repo.get_by_id(user_id) is None:
            raise UserNotFoundError(f"User {user_id!r} not found")

        role = self.rbac.get_role(payload.role_id)
        if role is None:
            raise RoleAssignmentNotFoundError(f"Role {payload.role_id} not found")

        # Build the (project_ids, organization_id) shape
        project_ids: List[Optional[str]]
        org_id: Optional[str] = None
        if payload.project_ids:
            project_ids = list(payload.project_ids)
        elif target_project_id:
            project_ids = [target_project_id]
        elif payload.project_id:
            project_ids = [payload.project_id]
        else:
            project_ids = [None]  # global or org-scoped
            org_id = payload.organization_id

        # Gate
        for pid in project_ids:
            self._assert_caller_can_grant(
                role_name=role.name,
                organization_id=org_id,
                project_id=pid,
                caller_user_id=caller_user_id,
                caller_is_admin=caller_is_admin,
            )

        results: List[RoleAssignmentResponse] = []
        for pid in project_ids:
            # Idempotent: skip if (user, role, scope) already exists
            existing = self.repo.find_existing(
                user_id=user_id,
                role_id=role.id,
                organization_id=org_id,
                project_id=pid,
            )
            if existing is not None:
                results.append(
                    self._to_response(existing, role=role, user=self.user_repo.get_by_id(user_id))
                )
                continue
            row = self.repo.create(
                user_id=user_id,
                role_id=role.id,
                organization_id=org_id,
                project_id=pid,
                created_by_user_id=caller_user_id,
            )
            results.append(
                self._to_response(row, role=role, user=self.user_repo.get_by_id(user_id))
            )

        self.db.commit()

        if payload.project_ids:
            return RoleAssignmentBatchResponse(items=results, total=len(results))
        return results[0]

    def delete(
        self,
        assignment_id: int,
        *,
        caller_user_id: str,
        caller_is_admin: bool,
    ) -> RoleAssignmentResponse:
        row = self.repo.get_by_id(assignment_id)
        if row is None:
            raise RoleAssignmentNotFoundError(f"Role assignment {assignment_id} not found")
        role = self.rbac.get_role(row.role_id)
        if role is None:
            raise RoleAssignmentNotFoundError("Role no longer exists")

        self._assert_caller_can_grant(
            role_name=role.name,
            organization_id=row.organization_id,
            project_id=row.project_id,
            caller_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
        )

        user = self.user_repo.get_by_id(row.user_id)
        response = self._to_response(row, role=role, user=user)
        self.repo.delete(row)
        self.db.commit()
        return response

    # ------------------------------------------------------------------ Doc-42b gate

    def _assert_caller_can_grant(
        self,
        *,
        role_name: str,
        organization_id: Optional[str],
        project_id: Optional[str],
        caller_user_id: str,
        caller_is_admin: bool,
    ) -> None:
        """Approximate Doc-42b rules for the first port. Refine later."""
        if role_name == SUPER_ADMIN_ROLE and not self._caller_is_super_admin(caller_user_id):
            raise CallerCannotGrantRoleError(
                f"Only super_admin can grant {SUPER_ADMIN_ROLE}",
                details={"role": role_name},
            )
        if caller_is_admin:
            return  # admin / super_admin grant freely (except above)
        # Non-admin grants — only org_admin / project_admin can grant, and only
        # within their scope. Project-scope grants are allowed when the project
        # belongs to the caller's vendor.
        caller = self.user_repo.get_by_id(caller_user_id)
        if caller is None:
            raise CallerCannotGrantRoleError("Caller not found")

        caller_perms = self.rbac.effective_permissions_for_user(caller_user_id)
        from app.core.permissions import RBAC_ASSIGN
        if RBAC_ASSIGN not in caller_perms:
            raise CallerCannotGrantRoleError(
                "Caller lacks rbac:assign permission",
            )

        # Coarse scope check: non-admin caller can only grant within their
        # vendor. Refine to per-role-tier rules in follow-up.
        if organization_id is not None:
            if caller.vendor_id != organization_id:
                raise CallerCannotGrantRoleError(
                    "Caller can only grant org-scoped roles in their own vendor",
                )
        if project_id is not None:
            owning_vendors = self.repo.project_owning_vendors(project_id)
            if caller.vendor_id is None or caller.vendor_id not in owning_vendors:
                raise CallerCannotGrantRoleError(
                    "Caller can only grant project-scoped roles on projects in their vendor",
                )

    def _caller_is_super_admin(self, caller_user_id: str) -> bool:
        super_role = self.rbac.get_role_by_name(SUPER_ADMIN_ROLE)
        if super_role is None:
            return False
        from sqlalchemy import select
        from app.models.user_role import UserRole
        return self.db.execute(
            select(UserRole.user_id)
            .where(UserRole.role_id == super_role.id)
            .where(UserRole.user_id == caller_user_id)
            .limit(1)
        ).first() is not None

    # ------------------------------------------------------------------ shaping

    def _to_response(
        self,
        assignment: UserRoleAssignment,
        *,
        role,
        user: Optional[User],
    ) -> RoleAssignmentResponse:
        if assignment.organization_id is not None:
            scope = "org"
        elif assignment.project_id is not None:
            scope = "project"
        else:
            scope = "global"
        return RoleAssignmentResponse(
            id=assignment.id,
            user_id=assignment.user_id,
            user_login=user.login if user else None,
            user_email=user.email if user else None,
            role_id=role.id,
            role_name=role.name,
            organization_id=assignment.organization_id,
            project_id=assignment.project_id,
            scope=scope,
            created_at=assignment.created_at,
            created_by=assignment.created_by,
        )
