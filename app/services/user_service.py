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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    CallerCannotModifyTargetError,
    ForbiddenError,
    LastSuperAdminLockoutError,
    UserEmailAlreadyInUseError,
    UserLoginAlreadyInUseError,
    UserNotFoundError,
)
from app.core.permissions import ADMIN_ROLE, SUPER_ADMIN_ROLE
from app.core.security import hash_password
from app.repositories.rbac_repository import RbacRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
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
        self.refresh_repo = RefreshTokenRepository(db)

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
        caller_can_see_all: bool = False,
    ):
        """Returns (rows, total).

        §3.1 (2026-06-02 audit) item 7: the broad-view bypass now keys on
        ``caller_can_see_all`` (caller holds ``users:read_all`` — admin
        and super_admin hold it via r005), not on ``caller_is_admin``.
        Non-broad callers are vendor-scoped + admin-tier-excluded.
        """
        broad = caller_is_admin or caller_can_see_all
        vendor_filter = None if broad else caller_vendor_id
        exclude_admin_tier = not broad
        return self.repo.list_(
            offset=offset,
            page_size=page_size,
            status=status,
            include_deleted=include_deleted,
            vendor_id_filter=vendor_filter,
            exclude_admin_tier=exclude_admin_tier,
        )

    def check_login_available(self, login: str) -> UserCheckLoginResponse:
        """Bug #138: a DELETED login is free to reuse — only live rows
        (deleted_at IS NULL, includes deactivated) reserve it."""
        existing = self.repo.get_by_login(login, include_deleted=False)
        return UserCheckLoginResponse(login=login, available=existing is None)

    # ------------------------------------------------------------------ create

    def create(
        self,
        payload: UserCreateRequest,
        *,
        created_by_user_id: Optional[str] = None,
        caller_is_admin: bool = False,
    ):
        """Single role-assignment path: ``orgRole`` is the role; ``project_ids``
        lists the projects and is honored ONLY for project-scoped roles
        (project_admin / project_member) — ignored for org/global roles.

        Every project-scoped grant is validated against the Doc-42b matrix via
        ``RoleAssignmentService._assert_caller_can_grant`` BEFORE the user row is
        committed, so an admin can't inject e.g. ``org_role="super_admin"`` and
        mint a peer/superior without holding the right grant authority.
        """
        # Bug #138: uniqueness is scoped to LIVE rows only — a deleted user's
        # login/email is free to reuse; a deactivated user's (deleted_at NULL)
        # stays reserved. The r020 partial unique index enforces this in the DB.
        if self.repo.get_by_login(payload.login, include_deleted=False) is not None:
            raise UserLoginAlreadyInUseError(
                f"Login {payload.login!r} already in use",
                details={"login": payload.login},
            )
        if self.repo.get_by_email(str(payload.email), include_deleted=False) is not None:
            raise UserEmailAlreadyInUseError(
                f"Email {payload.email!r} already in use",
                details={"email": str(payload.email)},
            )

        # §3.4.1 (2026-06-02 audit): the Rule-4 guard that exists on update()
        # also applies on create(). Refuse to mint a user whose org_role
        # column is admin/super_admin unless the caller is super_admin.
        # Closes the takeover path where an admin POSTs a new user with
        # org_role="super_admin" and instantly mints a peer-or-superior.
        if payload.org_role in (ADMIN_ROLE, SUPER_ADMIN_ROLE):
            if not (
                created_by_user_id is not None
                and self._caller_is_super_admin(created_by_user_id)
            ):
                raise ForbiddenError(
                    f"Only super_admin may create a user with "
                    f"org_role={payload.org_role!r}.",
                    code="RESERVED_ORG_ROLE_DENIED",
                    details={"org_role": payload.org_role},
                )

        # ONE path for project mapping: orgRole = the role, project_ids = the
        # projects. project_ids is honored ONLY for project-scoped roles
        # (project_admin / project_member); for org/global roles it is
        # meaningless and ignored (no validation, no rows). Validate the grant
        # for each project up-front (before the user row is created) so an
        # unauthorized caller can't self-assign (§3.4.1 2026-06-02 audit).
        from app.core.permissions import PROJECT_ONLY_ROLE_NAMES
        from app.services.role_assignment_service import RoleAssignmentService

        org_role_is_project = (
            (payload.org_role or "").strip().lower() in PROJECT_ONLY_ROLE_NAMES
        )
        scoped_project_ids = (
            list(payload.project_ids or []) if org_role_is_project else []
        )
        if scoped_project_ids and created_by_user_id is not None:
            vm_guard = RoleAssignmentService(self.db)
            vm_role = self.rbac.get_role_by_name(payload.org_role)
            if vm_role is not None:
                for pid in scoped_project_ids:
                    vm_guard._assert_caller_can_grant(
                        role_name=vm_role.name,
                        organization_id=None,
                        project_id=pid,
                        caller_user_id=created_by_user_id,
                        caller_is_admin=caller_is_admin,
                    )

        full_name = payload.full_name
        row = self.repo.create(
            login=payload.login,
            email=str(payload.email),
            hashed_password=hash_password(payload.password),
            full_name=full_name,
            phone_number=payload.phone_number,
            vendor_id=payload.vendor_id,
            division=payload.division,
            division_other=payload.division_other,
            org_role=payload.org_role,
            two_factor_enabled=payload.two_factor_enabled,
            user_code=generate_user_code(full_name or payload.login),
            status="active",
        )

        # Project-scoped role → one assignment per project, role taken from
        # orgRole. (scoped_project_ids is empty for org/global roles.)
        if scoped_project_ids:
            role = self.rbac.get_role_by_name(payload.org_role)
            if role is not None:
                for pid in scoped_project_ids:
                    self.assignments.create(
                        user_id=row.id,
                        role_id=role.id,
                        project_id=pid,
                        created_by_user_id=created_by_user_id,
                    )

        # Global / org-tier roles (admin, super_admin, org_admin, …) materialize
        # as a single GLOBAL org_role assignment. Project-only roles are never
        # held globally — they were scoped per-project above — so skip the global
        # sync for them (no error), which is what lets orgRole=<project role> +
        # project_ids work. Symmetric with PATCH /users/{id}.
        if (
            payload.org_role
            and created_by_user_id is not None
            and not org_role_is_project
        ):
            self._sync_org_role_assignment(
                target=row,
                new_org_role=payload.org_role,
                caller_user_id=created_by_user_id,
                caller_is_admin=caller_is_admin,
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
        """Doc-44 Flow 1: self-edit OR caller holding the per-field code.

        Field-level enforcement: for non-self callers, every touched field
        must have a corresponding `users:update:<field>` permission held by
        the caller. Admins/super_admin pass because r005 grants them every
        field code — A1 (2026-06-02 audit) removed the implicit bypass.

        org_admin/project_admin can NOT edit other users' rows (round-7
        decision Q1) — they manage role-assignments, not user-row fields.
        """
        target = self.get_by_id(user_id)
        self._assert_caller_can_modify_user(
            caller_user_id, target, caller_is_admin, request=request,
        )

        updates = payload.model_dump(exclude_unset=True)
        # §3.7 (2026-06-02 audit): compute `touched` BEFORE the pops below
        # so future field_codes additions (e.g. full_name, project_ids,
        # admin) won't silently bypass the walker if a code is later mapped.
        touched = set(updates.keys())
        # full_name is written directly (gated by users:update:full_name via
        # the field-walker). No more first_name/last_name split.
        # project_ids replacement is handled by role-assignment routes; ignore here.
        updates.pop("project_ids", None)
        updates.pop("admin", None)
        if not updates:
            return target

        # Field-level gate. Self-edit bypasses; otherwise the caller must
        # hold the corresponding ``users:update:<field>`` code.
        if request is not None and caller_user_id != target.id:
            from app.core.permissions import USER_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=USER_FIELD_CODES,
                touched_fields=touched,
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

        # A3 (2026-06-02 audit): refuse to flip a user's org_role to
        # admin or super_admin unless the caller is super_admin. This
        # closes the takeover path where an admin could PATCH another
        # user's row to elevate them.
        if "org_role" in updates:
            requested_org_role = updates.get("org_role")
            if requested_org_role in (ADMIN_ROLE, SUPER_ADMIN_ROLE):
                if not self._caller_is_super_admin(caller_user_id):
                    raise ForbiddenError(
                        f"Only super_admin may set a user's org_role to "
                        f"{requested_org_role!r}.",
                        code="RESERVED_ORG_ROLE_DENIED",
                        details={"org_role": requested_org_role},
                    )

        # Doc-45 round-9b extension: when the PATCH supplies org_role, also
        # sync the GLOBAL org-tier role-assignment so the user actually gets
        # the permissions. The column on its own is decorative; the matching
        # row in user_role_assignments is what authorizes. Existing scoped
        # assignments (org / project) are left untouched — only globally-
        # scoped org-tier rows are managed by this sync.
        if "org_role" in updates:
            self._sync_org_role_assignment(
                target=target,
                new_org_role=updates["org_role"],
                caller_user_id=caller_user_id,
                caller_is_admin=caller_is_admin,
            )

        self.repo.update(target, **updates)
        self.db.commit()
        return target

    def _sync_org_role_assignment(
        self,
        *,
        target,
        new_org_role,
        caller_user_id: str,
        caller_is_admin: bool,
    ) -> None:
        """Keep the global org-tier user_role_assignment in sync with the
        user's org_role column on PATCH /users/{id}.

        Behavior:
          * new_org_role normalized to lowercase string; null/empty → "clear"
          * Non-empty value must match a ``builtin=True`` row in
            ``users.roles``. test_role and any other custom (builtin=False)
            role → 422 ValidationError. 2026-06-02: this validation is now
            DB-driven instead of hand-maintained, so new builtin roles
            added via migration are automatically accepted.
          * Permission gate: reuses RoleAssignmentService._assert_caller_can_grant
            so the same caller-tier rules apply (only super_admin can grant
            super_admin / admin, etc.).
          * Last-super-admin lockout: if the target is the only super_admin
            and the new value is NOT super_admin, refuse to avoid locking the
            instance out of admin access.
          * Atomic delete-then-create within the surrounding update()
            transaction: remove every globally-scoped builtin-role row for
            the target, then insert one fresh row for the new tier (if any).
        """
        from app.core.errors import ValidationError
        from app.repositories.user_role_assignment_repository import UserRoleAssignmentRepository
        from app.services.role_assignment_service import RoleAssignmentService

        normalized = (new_org_role or "").strip().lower() or None

        if normalized is not None:
            from app.models.role import Role
            role_row = self.db.execute(
                select(Role).where(Role.name == normalized).where(Role.builtin.is_(True))
            ).scalar_one_or_none()
            if role_row is None:
                allowed = sorted(self.db.execute(
                    select(Role.name).where(Role.builtin.is_(True))
                ).scalars())
                raise ValidationError(
                    f"org_role must be a builtin role name (or null to clear). "
                    f"Got {new_org_role!r}. Allowed: {allowed}.",
                    details={"field": "org_role", "value": new_org_role,
                             "allowed": allowed},
                )

        # Last-super-admin lockout: target currently is super_admin (via any
        # path) and the new value isn't super_admin → refuse.
        if normalized != SUPER_ADMIN_ROLE and self._is_only_super_admin(target.id):
            raise LastSuperAdminLockoutError(
                "Cannot strip the last remaining super_admin of their tier.",
                details={"target_user_id": target.id},
            )

        # Permission gate — only run when actually assigning a new tier.
        # Reuses the existing matrix + caller-tier rules so we don't drift.
        if normalized is not None:
            ra_service = RoleAssignmentService(self.db)
            ra_service._assert_caller_can_grant(
                role_name=normalized,
                organization_id=None,
                project_id=None,
                caller_user_id=caller_user_id,
                caller_is_admin=caller_is_admin,
            )

        # Delete every globally-scoped builtin-role assignment the target
        # currently holds. Scoped assignments (org_id / project_id set) are
        # NOT touched — those represent per-project membership and live
        # independently. Non-builtin (custom) roles are also untouched so
        # things like `test_role` aren't accidentally swept.
        ra_repo = UserRoleAssignmentRepository(self.db)
        existing_pairs = ra_repo.list_by_user(target.id)
        for assignment, role in existing_pairs:
            is_global = assignment.organization_id is None and assignment.project_id is None
            if is_global and getattr(role, "builtin", False):
                ra_repo.delete(assignment)

        # Insert the new globally-scoped assignment for the requested tier
        # (skip when clearing).
        if normalized is not None:
            new_role = self.rbac.get_role_by_name(normalized)
            if new_role is None:
                # The validation above already confirmed the role exists +
                # is builtin via DB query. If we're here the row was
                # deleted between the validation and this insert (race) —
                # treat as 500-class.
                raise ValidationError(
                    f"Role {normalized!r} disappeared between validation "
                    f"and assignment. Retry.",
                )
            ra_repo.create(
                user_id=target.id,
                role_id=new_role.id,
                organization_id=None,
                project_id=None,
                created_by_user_id=caller_user_id,
            )

        # Clear-case workaround: UserRepository.update() silently skips
        # None-valued kwargs (only writes non-None fields), so org_role=null
        # in the PATCH body wouldn't otherwise reach the DB. Set the ORM
        # attribute directly here; SQLAlchemy emits the UPDATE on flush.
        if normalized is None:
            target.org_role = None

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
        self.refresh_repo.revoke_all_for_user(target.id)
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
        self.refresh_repo.revoke_all_for_user(target.id)
        self.db.commit()
        return target

    def restore(self, user_id: str, *, caller_user_id: str, caller_is_admin: bool, request=None):
        target = self.get_by_id(user_id)
        self._assert_caller_can_delete_user(caller_user_id, target, caller_is_admin, request)
        # Bug #138: the login/email may have been reused by a live user while
        # this row was deleted. Restoring would re-collide on the r020 partial
        # unique index — surface a clear 409 instead of a raw IntegrityError.
        login_clash = self.repo.get_by_login(target.login, include_deleted=False)
        if login_clash is not None and login_clash.id != target.id:
            raise UserLoginAlreadyInUseError(
                f"Login {target.login!r} is now in use by another user; "
                "change it before restoring",
                details={"login": target.login},
            )
        email_clash = self.repo.get_by_email(target.email, include_deleted=False)
        if email_clash is not None and email_clash.id != target.id:
            raise UserEmailAlreadyInUseError(
                f"Email {target.email!r} is now in use by another user; "
                "change it before restoring",
                details={"email": target.email},
            )
        self.repo.restore(target)
        self.db.commit()
        return target

    # ------------------------------------------------------------------ Doc-44 gates (round-7)

    def _assert_caller_can_modify_user(
        self, caller_user_id: str, target, caller_is_admin: bool, request=None,
    ):
        """Flow 1 gate: PATCH /user/users/{id}/update.

        §3.1 (2026-06-02 audit) item 1: replaced ``caller_is_admin`` short-
        circuit with an explicit capability check. Caller passes if they
        hold ANY ``users:update:*`` field code globally — the field walker
        then determines which specific fields they can write. Admins still
        pass because r005 grants every field code to admin/super_admin.

        Allowed:
          - Self-edit (caller is the target).
          - Anyone holding at least one ``users:update:*`` code globally.

        Field-level enforcement runs AFTER this gate in ``update()``.
        """
        if caller_user_id == target.id:
            return
        if request is not None:
            from app.core.permissions import USER_FIELD_CODES

            held = getattr(request.state, "user_permissions", None) or set()
            if any(c in held for c in USER_FIELD_CODES.values()):
                return
        raise CallerCannotModifyTargetError(
            "Only the account owner or a caller holding users:update:* can "
            "modify this user's profile",
            details={"target_user_id": target.id},
        )

    def _assert_caller_can_delete_user(
        self, caller_user_id: str, target, caller_is_admin: bool, request,
    ):
        """Flow 3 gate: DELETE /user/users/{id}/delete (and /restore).

        §3.1 (2026-06-02 audit) item 2: replaced the ``caller_is_admin``
        short-circuit with explicit code checks. Caller passes if they hold
        ``users:delete_all`` globally, OR ``users:delete_vendor`` at
        ("org", target.vendor_id). Admin holds users:delete_all via r005.

        Allowed:
          - Anyone holding USERS_DELETE_ALL globally.
          - Anyone holding USERS_DELETE_VENDOR scoped to target.vendor_id.

        Self-delete is NOT allowed (admins delete users, not themselves; the
        last-super-admin lockout already guards the dangerous case).
        """
        from app.core.permissions import USERS_DELETE_ALL, USERS_DELETE_VENDOR

        if request is not None:
            scoped = getattr(request.state, "scoped_permissions", None) or {}
            held_flat = getattr(request.state, "user_permissions", None) or set()
            if USERS_DELETE_ALL in held_flat:
                return
            if target.vendor_id and USERS_DELETE_VENDOR in scoped.get(
                ("org", target.vendor_id), set()
            ):
                return
        raise CallerCannotModifyTargetError(
            "You don't have authority to delete this user",
            details={"target_user_id": target.id},
        )

    def _caller_is_super_admin(self, caller_user_id: Optional[str]) -> bool:
        """True if `caller_user_id` holds the super_admin role via legacy
        user_roles OR a global user_role_assignment. Used by A3 takeover
        guards (2026-06-02 audit).
        """
        if not caller_user_id:
            return False
        from sqlalchemy import select
        from app.models.user_role import UserRole
        from app.models.user_role_assignment import UserRoleAssignment

        super_role = self.rbac.get_role_by_name(SUPER_ADMIN_ROLE)
        if super_role is None:
            return False

        legacy = self.db.execute(
            select(UserRole.user_id)
            .where(UserRole.role_id == super_role.id)
            .where(UserRole.user_id == caller_user_id)
            .limit(1)
        ).first()
        if legacy is not None:
            return True

        scoped = self.db.execute(
            select(UserRoleAssignment.user_id)
            .where(UserRoleAssignment.role_id == super_role.id)
            .where(UserRoleAssignment.user_id == caller_user_id)
            .where(UserRoleAssignment.organization_id.is_(None))
            .where(UserRoleAssignment.project_id.is_(None))
            .limit(1)
        ).first()
        return scoped is not None

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
