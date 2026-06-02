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

from typing import Dict, List, Optional, Tuple

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
        # Resolve project_code once per call (all rows share the same project).
        project_code = self._project_code_for(project_id)
        return [
            self._to_response(a, role=r, user=u, project_code=project_code)
            for a, r, u in rows
        ]

    def _project_code_for(self, project_id: Optional[str]) -> Optional[str]:
        """Look up project_code via the cross-schema Project mirror. Returns
        None for global/org-scoped grants or missing projects."""
        if not project_id:
            return None
        from app.models._cross_schema import Project as ProjectMirror
        proj = self.db.get(ProjectMirror, project_id)
        return proj.project_code if proj is not None else None

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

    # §3.4.3 (2026-06-02 audit): team-management endpoint may only assign
    # the two project-scoped tiers. Stops the §3.3+§3.4.3 combo where admin
    # could PUT assignments={"super_admin": [admin_id]} on any project and
    # inherit global super_admin powers via the universal-tier projection.
    # New roles (e.g. "project_observer") must be added here explicitly.
    _BULK_REPLACE_ALLOWED_ROLES = frozenset({PROJECT_ADMIN_ROLE, PROJECT_MEMBER_ROLE})

    def bulk_replace_for_project(
        self,
        project_id: str,
        assignments: Dict[str, List[str]],
        *,
        caller_user_id: str,
        caller_is_admin: bool,
    ) -> List[RoleAssignmentResponse]:
        """Full-replace the specified roles for a project (Manage-Team Submit).

        The route gate (PROJECT_MEMBERS_UPDATE) already verified the caller
        is allowed to manage team members. We skip the rbac:assign / vendor-
        linkage checks here — those are for RBAC delegation (granting
        arbitrary roles), not for the team-management use case.

        §3.4.3: role_name is whitelisted to {project_admin, project_member};
        every other role (including admin/super_admin/custom-with-admin-codes)
        is refused here. RBAC delegation paths must go through
        ``create()`` / ``_assert_caller_can_grant``.

        For each whitelisted role_name in `assignments`:
          1. Look up the role; raise 404 if unknown.
          2. Delete all existing rows for (project_id, role).
          3. Insert one row per user_id (skips unknown users silently).
        Roles not listed are left unchanged.
        Commits once at the end.
        """
        bad_roles = sorted(set(assignments.keys()) - self._BULK_REPLACE_ALLOWED_ROLES)
        if bad_roles:
            raise CallerCannotGrantRoleError(
                f"Role(s) {bad_roles!r} cannot be assigned via the team-"
                f"management endpoint. Allowed: "
                f"{sorted(self._BULK_REPLACE_ALLOWED_ROLES)!r}.",
                details={
                    "rejected_roles": bad_roles,
                    "allowed_roles": sorted(self._BULK_REPLACE_ALLOWED_ROLES),
                },
            )
        for role_name, user_ids in assignments.items():
            role = self.rbac.get_role_by_name(role_name)
            if role is None:
                raise RoleAssignmentNotFoundError(f"Role {role_name!r} not found")

            self.repo.delete_by_project_and_role(project_id, role.id)
            for uid in set(user_ids):
                if self.user_repo.get_by_id(uid) is None:
                    continue
                self.repo.create(
                    user_id=uid,
                    role_id=role.id,
                    project_id=project_id,
                    created_by_user_id=caller_user_id,
                )

        self.db.commit()
        return self.list_for_project(project_id)

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
        """Round-8 C4/H3 (monolith parity): consult the Doc-42b matrix
        server-side, not just on the FE picker.

        Hard rules (applied first, before the matrix):
          1. The `admin` and `super_admin` roles are GLOBAL-ONLY. Any attempt
             to assign them at org/project scope is refused. (Prevents C5
             where a scoped admin would inherit global is_admin.)
          2. Only `super_admin` may grant the `super_admin` role.
          3. Only `super_admin` may grant the `admin` role. (Monolith parity:
             PMIS-user-management/.../role_assignments/services.py:188-194.)

        Then the matrix:
          4. The caller's effective set of role names is computed from
             user_roles + global user_role_assignments.
          5. For the requested (target_role_name, scope_kind), at least one
             of the caller's role names must permit that exact (name, scope)
             pair in role_grants_service._MATRIX. (Closes C4 — admin can no
             longer grant arbitrary roles bypassing the matrix.)
          6. For non-global scope, the caller must also be linked to the
             organization (vendor_id match) or project (vendor of project
             matches caller.vendor_id).

        Non-admin callers additionally need the `rbac:assign` permission.
        """
        from app.core.permissions import (
            ADMIN_ROLE,
            LOCKED_ROLE_NAMES,
            RBAC_ASSIGN,
        )
        from app.services.role_grants_service import is_grant_allowed

        # ---- (1) scope guard on admin/super_admin --------------------------
        is_scoped = organization_id is not None or project_id is not None
        if role_name in LOCKED_ROLE_NAMES and is_scoped:
            raise CallerCannotGrantRoleError(
                f"Role {role_name!r} can only be assigned globally "
                f"(organization_id and project_id must be NULL).",
                details={
                    "role": role_name,
                    "organization_id": organization_id,
                    "project_id": project_id,
                },
            )

        # ---- (2) super_admin grant requires super_admin caller ------------
        caller_is_super = self._caller_is_super_admin(caller_user_id)
        if role_name == SUPER_ADMIN_ROLE and not caller_is_super:
            raise CallerCannotGrantRoleError(
                f"Only super_admin can grant {SUPER_ADMIN_ROLE}",
                details={"role": role_name},
            )

        # ---- (3) admin grant requires super_admin caller -------------------
        if role_name == ADMIN_ROLE and not caller_is_super:
            raise CallerCannotGrantRoleError(
                f"Only super_admin can grant {ADMIN_ROLE} (round-8 H3).",
                details={"role": role_name},
            )

        # super_admin caller passes all remaining checks (full grantor power
        # except the locked rules already enforced above).
        if caller_is_super:
            return

        # ---- (4) compute caller's effective role-name set ------------------
        caller_role_names = self._caller_role_names(caller_user_id)
        if not caller_role_names:
            raise CallerCannotGrantRoleError(
                "Caller has no role assignments capable of granting roles.",
            )

        # rbac:assign is required for any non-super_admin grantor.
        caller_perms = self.rbac.effective_permissions_for_user(caller_user_id)
        if RBAC_ASSIGN not in caller_perms:
            raise CallerCannotGrantRoleError(
                "Caller lacks rbac:assign permission",
            )

        # ---- (5) matrix consultation (closes C4) ---------------------------
        scope_kind = (
            "project" if project_id is not None
            else "org" if organization_id is not None
            else "global"
        )
        if not is_grant_allowed(
            caller_role_names=caller_role_names,
            target_role_name=role_name,
            scope_kind=scope_kind,
        ):
            raise CallerCannotGrantRoleError(
                f"Caller's role(s) {sorted(caller_role_names)!r} cannot grant "
                f"{role_name!r} at {scope_kind!r} scope. See "
                f"GET /user/role-grants/{{role_name}}/matrix for what each "
                f"role may grant.",
                details={
                    "caller_roles": sorted(caller_role_names),
                    "target_role": role_name,
                    "scope_kind": scope_kind,
                },
            )

        # ---- (6) vendor-of-target check for org/project scope --------------
        if organization_id is not None or project_id is not None:
            caller = self.user_repo.get_by_id(caller_user_id)
            if caller is None:
                raise CallerCannotGrantRoleError("Caller not found")
            if organization_id is not None and caller.vendor_id != organization_id:
                raise CallerCannotGrantRoleError(
                    "Caller can only grant org-scoped roles in their own vendor",
                )
            if project_id is not None:
                owning_vendors = self.repo.project_owning_vendors(project_id)
                if caller.vendor_id is None or caller.vendor_id not in owning_vendors:
                    raise CallerCannotGrantRoleError(
                        "Caller can only grant project-scoped roles on "
                        "projects in their vendor",
                    )

    def _caller_is_super_admin(self, caller_user_id: str) -> bool:
        """Round-8: a user is super_admin only when bound at GLOBAL scope
        via either tier — the C5 scope filter for admin lookups."""
        super_role = self.rbac.get_role_by_name(SUPER_ADMIN_ROLE)
        if super_role is None:
            return False
        from sqlalchemy import select
        from app.models.user_role import UserRole
        from app.models.user_role_assignment import UserRoleAssignment

        # Legacy global tier
        if self.db.execute(
            select(UserRole.user_id)
            .where(UserRole.role_id == super_role.id)
            .where(UserRole.user_id == caller_user_id)
            .limit(1)
        ).first():
            return True
        # Doc-41 global-only scope (round-8 C5)
        return self.db.execute(
            select(UserRoleAssignment.id)
            .where(UserRoleAssignment.role_id == super_role.id)
            .where(UserRoleAssignment.user_id == caller_user_id)
            .where(UserRoleAssignment.organization_id.is_(None))
            .where(UserRoleAssignment.project_id.is_(None))
            .limit(1)
        ).first() is not None

    def _caller_role_names(self, caller_user_id: str) -> set[str]:
        """Round-8 C4: return every role name the caller holds via either
        tier. GLOBAL-only for super_admin/admin (per C5 scope rule);
        all-scopes for the other tiers since their grant authority is
        scope-bounded elsewhere (step 6 of _assert_caller_can_grant).
        """
        from sqlalchemy import select
        from app.models.role import Role
        from app.models.user_role import UserRole
        from app.models.user_role_assignment import UserRoleAssignment

        names: set[str] = set()
        # Legacy global tier
        for (name,) in self.db.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == caller_user_id)
        ).all():
            names.add(name)
        # Doc-41 scoped tier — gather all role names, regardless of scope
        # (matrix step ensures scope-bounded use).
        for (name,) in self.db.execute(
            select(Role.name)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == caller_user_id)
        ).all():
            names.add(name)
        return names

    # ------------------------------------------------------------------ shaping

    def _to_response(
        self,
        assignment: UserRoleAssignment,
        *,
        role,
        user: Optional[User],
        project_code: Optional[str] = None,
    ) -> RoleAssignmentResponse:
        if assignment.organization_id is not None:
            scope = "org"
        elif assignment.project_id is not None:
            scope = "project"
        else:
            scope = "global"
        # Default project_code lookup for callers that didn't pre-resolve
        # (single-create / single-update paths). list_for_project resolves
        # once per call and threads it through to avoid N+1 queries.
        if project_code is None and assignment.project_id is not None:
            project_code = self._project_code_for(assignment.project_id)
        return RoleAssignmentResponse(
            id=assignment.id,
            user_id=assignment.user_id,
            user_login=user.login if user else None,
            user_email=user.email if user else None,
            role_id=role.id,
            role_name=role.name,
            organization_id=assignment.organization_id,
            project_id=assignment.project_id,
            project_code=project_code,
            scope=scope,
            created_at=assignment.created_at,
            created_by=assignment.created_by,
        )
