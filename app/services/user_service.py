"""UserService — user CRUD + Doc-44 caller-vs-target gates + Doc-46 list filters.

Doc-44 caller-vs-target (simplified for first port; refine in follow-up):
  - super_admin: can modify anyone
  - admin: can modify anyone except super_admin holders
  - org_admin / project_admin: can modify users sharing their vendor scope
  - others: only their own record

Doc-46 list scoping:
  - non-admin caller: filter to caller's own vendor_id
  - non-admin caller: exclude admin-tier users (NOT EXISTS subquery in repo)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.errors import (
    CallerCannotModifyTargetError,
    LastSuperAdminLockoutError,
    UserEmailAlreadyInUseError,
    UserLoginAlreadyInUseError,
    UserNotFoundError,
)
from app.core.permissions import SUPER_ADMIN_ROLE
from app.core.security import hash_password
from app.repositories.rbac_repository import RbacRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_role_assignment_repository import UserRoleAssignmentRepository
from app.schemas.user import (
    UserCheckLoginResponse,
    UserCreateRequest,
    UserPasswordUpdateRequest,
    UserUpdateRequest,
)
from app.utilities.code_generators import generate_user_code


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)
        self.rbac = RbacRepository(db)
        self.assignments = UserRoleAssignmentRepository(db)

    # ------------------------------------------------------------------ read

    def get_by_id(self, user_id: str):
        row = self.repo.get_by_id(user_id)
        if row is None:
            raise UserNotFoundError(f"User {user_id!r} not found")
        return row

    def list_(
        self,
        *,
        offset: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        include_deleted: bool = False,
        caller_vendor_id: Optional[str] = None,
        caller_is_admin: bool = False,
    ):
        """Returns (rows, total). Non-admin callers are vendor-scoped + admin-tier-excluded."""
        vendor_filter = None if caller_is_admin else caller_vendor_id
        exclude_admin_tier = not caller_is_admin
        return self.repo.list_(
            offset=offset,
            page_size=page_size,
            status=status,
            include_deleted=include_deleted,
            vendor_id_filter=vendor_filter,
            exclude_admin_tier=exclude_admin_tier,
        )

    def check_login_available(self, login: str) -> UserCheckLoginResponse:
        """Includes soft-deleted users (matches monolith behavior — a deleted
        login is reserved until the row is hard-removed)."""
        existing = self.repo.get_by_login(login, include_deleted=True)
        return UserCheckLoginResponse(login=login, available=existing is None)

    # ------------------------------------------------------------------ create

    def create(
        self,
        payload: UserCreateRequest,
        *,
        created_by_user_id: Optional[str] = None,
        caller_is_admin: bool = False,
    ):
        """Round-8 C2: each `project_assignments[i].role_id` is now validated
        against the Doc-42b matrix BEFORE the user row is committed.

        Previously this method wrote directly to UserRoleAssignmentRepository,
        bypassing `RoleAssignmentService._assert_caller_can_grant` — an admin
        could thus inject `role_id=<super_admin>` via the user-create body
        and mint a super_admin without holding `users:grant_superadmin`.
        Now every assignment passes through the same matrix the standalone
        role-assignment endpoint uses.
        """
        # Uniqueness checks against active + soft-deleted rows.
        if self.repo.get_by_login(payload.login, include_deleted=True) is not None:
            raise UserLoginAlreadyInUseError(
                f"Login {payload.login!r} already in use",
                details={"login": payload.login},
            )
        if self.repo.get_by_email(str(payload.email), include_deleted=True) is not None:
            raise UserEmailAlreadyInUseError(
                f"Email {payload.email!r} already in use",
                details={"email": str(payload.email)},
            )

        # Round-8 C2: validate each project_assignment against the matrix
        # BEFORE creating the user. We resolve every role_id to its name,
        # then call the same guard `_assert_caller_can_grant` that the
        # /role-assignments/create route uses.
        if payload.project_assignments and created_by_user_id is not None:
            from app.services.role_assignment_service import RoleAssignmentService

            grant_guard = RoleAssignmentService(self.db)
            for assignment in payload.project_assignments:
                role = self.rbac.get_role(assignment.role_id)
                if role is None:
                    raise UserNotFoundError(
                        f"Role {assignment.role_id} in project_assignments[] "
                        f"does not exist."
                    )
                grant_guard._assert_caller_can_grant(
                    role_name=role.name,
                    organization_id=None,
                    project_id=assignment.project_id,
                    caller_user_id=created_by_user_id,
                    caller_is_admin=caller_is_admin,
                )

        first_name = payload.first_name
        last_name = payload.last_name
        full_name = " ".join(filter(None, [first_name, last_name])) or payload.login
        row = self.repo.create(
            login=payload.login,
            email=str(payload.email),
            hashed_password=hash_password(payload.password),
            first_name=first_name,
            last_name=last_name,
            phone_number=payload.phone_number,
            vendor_id=payload.vendor_id,
            division=payload.division,
            division_other=payload.division_other,
            org_role=payload.org_role,
            two_factor_enabled=payload.two_factor_enabled,
            user_code=generate_user_code(full_name),
            status="active",
        )

        # Legacy project_assignments[] (local format: {project_id, role_id}).
        for assignment in payload.project_assignments:
            self.assignments.create(
                user_id=row.id,
                role_id=assignment.role_id,
                project_id=assignment.project_id,
                created_by_user_id=created_by_user_id,
            )

        # VM-style: project_ids + org_role — create one scoped assignment per project.
        if payload.project_ids and payload.org_role:
            role = self.rbac.get_role_by_name(payload.org_role)
            if role is not None:
                already_assigned = {a.project_id for a in payload.project_assignments}
                for pid in payload.project_ids:
                    if pid not in already_assigned:
                        self.assignments.create(
                            user_id=row.id,
                            role_id=role.id,
                            project_id=pid,
                            created_by_user_id=created_by_user_id,
                        )

        self.db.commit()
        return row

    # ------------------------------------------------------------------ update

    def update(
        self,
        user_id: str,
        payload: UserUpdateRequest,
        *,
        request,
        caller_user_id: str,
        caller_is_admin: bool,
    ):
        """Doc-44 Flow 1 (round-7): self-only OR admin/super_admin.

        Field-level enforcement: for non-self callers, every touched field
        must have a corresponding `users:update:<field>` permission held by
        the caller. (Admins bypass field-level checks at the helper.)

        org_admin/project_admin can NOT edit other users' rows (round-7
        decision Q1) — they manage role-assignments, not user-row fields.
        """
        target = self.get_by_id(user_id)
        self._assert_caller_can_modify_user(caller_user_id, target, caller_is_admin)

        updates = payload.model_dump(exclude_unset=True)
        # Split full_name → first_name / last_name when present
        if "full_name" in updates and updates["full_name"]:
            parts = updates.pop("full_name").split(None, 1)
            if "first_name" not in updates:
                updates["first_name"] = parts[0] if parts else None
            if "last_name" not in updates:
                updates["last_name"] = parts[1] if len(parts) > 1 else None
        else:
            updates.pop("full_name", None)
        # project_ids replacement is handled by role-assignment routes; ignore here.
        updates.pop("project_ids", None)
        updates.pop("admin", None)
        if not updates:
            return target

        # Field-level gate. Self-edit and admin bypass the gate (admin via
        # the helper's _is_admin shortcut; self via this branch).
        if request is not None and caller_user_id != target.id:
            from app.core.permissions import USER_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=USER_FIELD_CODES,
                touched_fields=set(updates.keys()),
            )

        if "email" in updates and updates["email"] is not None:
            email = str(updates["email"])
            existing = self.repo.get_by_email(email, include_deleted=True)
            if existing is not None and existing.id != target.id:
                raise UserEmailAlreadyInUseError(
                    f"Email {email!r} already in use",
                    details={"email": email},
                )
            updates["email"] = email

        self.repo.update(target, **updates)
        self.db.commit()
        return target

    def update_password(
        self,
        user_id: str,
        payload: UserPasswordUpdateRequest,
        *,
        caller_user_id: str,
    ):
        """Doc-44 Flow 2 (round-7): SELF-ONLY.

        Admin-driven password reset is removed. New users / forgotten
        passwords go through the self-service forgot-password / reset-password
        flow (anti-enum). Logged-in users change their own password here.
        """
        if caller_user_id != user_id:
            raise CallerCannotModifyTargetError(
                "Password can only be changed by the account owner. "
                "Other users use the forgot-password flow.",
                details={"target_user_id": user_id},
            )
        target = self.get_by_id(user_id)
        self.repo.set_password(target, hash_password(payload.password))
        # Invalidate refresh state — force re-login after password change.
        self.repo.rotate_refresh_token(target, new_jti=None, grace_seconds=0)
        self.db.commit()
        return target

    # ------------------------------------------------------------------ delete / restore

    def delete(self, user_id: str, *, caller_user_id: str, caller_is_admin: bool, request=None):
        """Doc-44 Flow 3 (round-7): admin/super_admin globally OR
        org_admin scoped to the target's vendor.

        org_admin can delete users in their own vendor; cannot delete admins
        or users in other vendors. (org_admin still cannot CREATE users —
        users:create stays admin-only.)
        """
        target = self.get_by_id(user_id)
        self._assert_caller_can_delete_user(caller_user_id, target, caller_is_admin, request)
        if self._is_only_super_admin(target.id):
            raise LastSuperAdminLockoutError(
                "Cannot delete the only remaining super_admin",
            )
        self.repo.soft_delete(target, deleted_by_user_id=caller_user_id)
        # Revoke refresh tokens
        self.repo.rotate_refresh_token(target, new_jti=None, grace_seconds=0)
        self.db.commit()
        return target

    def restore(self, user_id: str, *, caller_user_id: str, caller_is_admin: bool, request=None):
        target = self.get_by_id(user_id)
        self._assert_caller_can_delete_user(caller_user_id, target, caller_is_admin, request)
        self.repo.restore(target)
        self.db.commit()
        return target

    # ------------------------------------------------------------------ Doc-44 gates (round-7)

    def _assert_caller_can_modify_user(
        self, caller_user_id: str, target, caller_is_admin: bool,
    ):
        """Flow 1 gate: PATCH /user/users/{id}/update.

        Allowed:
          - Self-edit (caller is the target).
          - admin / super_admin (any target).

        Disallowed:
          - Anyone else, including same-vendor non-admins. org_admin and
            project_admin manage role-assignments, not user-row fields
            (round-7 Q1).

        Field-level enforcement runs AFTER this gate in `update()`.
        """
        if caller_user_id == target.id:
            return
        if caller_is_admin:
            return
        raise CallerCannotModifyTargetError(
            "Only the account owner or an admin can modify this user's profile",
            details={"target_user_id": target.id},
        )

    def _assert_caller_can_delete_user(
        self, caller_user_id: str, target, caller_is_admin: bool, request,
    ):
        """Flow 3 gate: DELETE /user/users/{id}/delete (and /restore).

        Allowed:
          - admin / super_admin (any target).
          - org_admin holding `users:delete_vendor` scoped to a vendor that
            equals target.vendor_id.

        Implementation: ask the scoped_permissions map whether the caller
        holds USERS_DELETE_VENDOR at ("org", target.vendor_id). If yes, allow.
        Otherwise require caller_is_admin.

        Self-delete is NOT allowed (admins delete users, not themselves; the
        last-super-admin lockout already guards the dangerous case).
        """
        if caller_is_admin:
            return
        if request is not None and target.vendor_id:
            from app.core.permissions import USERS_DELETE_VENDOR

            scoped = getattr(request.state, "scoped_permissions", None) or {}
            if USERS_DELETE_VENDOR in scoped.get(("org", target.vendor_id), set()):
                return
        raise CallerCannotModifyTargetError(
            "You don't have authority to delete this user",
            details={"target_user_id": target.id},
        )

    def _is_only_super_admin(self, user_id: str) -> bool:
        """True if this user holds super_admin AND no other user does."""
        from sqlalchemy import select
        from app.models.user_role import UserRole
        from app.models.user_role_assignment import UserRoleAssignment

        super_role = self.rbac.get_role_by_name(SUPER_ADMIN_ROLE)
        if super_role is None:
            return False

        # Find users with super_admin (via either tier) excluding the target
        legacy_others = self.db.execute(
            select(UserRole.user_id)
            .where(UserRole.role_id == super_role.id)
            .where(UserRole.user_id != user_id)
            .limit(1)
        ).first()
        if legacy_others:
            return False
        scoped_others = self.db.execute(
            select(UserRoleAssignment.user_id)
            .where(UserRoleAssignment.role_id == super_role.id)
            .where(UserRoleAssignment.user_id != user_id)
            .limit(1)
        ).first()
        if scoped_others:
            return False

        # Confirm target IS a super_admin (otherwise lockout doesn't apply)
        target_legacy = self.db.execute(
            select(UserRole.user_id)
            .where(UserRole.role_id == super_role.id)
            .where(UserRole.user_id == user_id)
            .limit(1)
        ).first()
        if target_legacy:
            return True
        target_scoped = self.db.execute(
            select(UserRoleAssignment.user_id)
            .where(UserRoleAssignment.role_id == super_role.id)
            .where(UserRoleAssignment.user_id == user_id)
            .limit(1)
        ).first()
        return target_scoped is not None
