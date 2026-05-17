"""Bootstrap data-migration for pmis-user-management.

Seeds (all idempotent — uses ON CONFLICT DO NOTHING):
  1. Every permission code declared in app/core/permissions.py:ALL_PERMISSIONS
     into users.permissions (is_builtin=True).
  2. Six built-in roles into users.roles:
        - super_admin
        - admin
        - org_admin
        - project_admin
        - project_member
        - division_member
  3. role_permissions grants per role tier (see _grants_by_role below).
  4. The bootstrap super_admin user (Q33: password sourced from
     SUPERADMIN_BOOTSTRAP_PASSWORD env var; row skipped if unset).
  5. Legacy user_roles row binding that super_admin user to the super_admin
     role (so AuthMiddleware's user_has_admin_role check fires on first
     login even before any user_role_assignments are written).

Role-permission grants (canonical):
  - super_admin: ALL_PERMISSIONS (incl. users:grant_superadmin).
  - admin:      ALL_PERMISSIONS \\ {users:grant_superadmin}.
  - org_admin:  user reads + RBAC assign + project-domain perms (R/W mid-tier)
                + ALL_MASTERS_READ_PERMISSIONS.
  - project_admin: project-domain R/W perms + members R/W + masters reads +
                   users:read (so they can pick assignees in their scope).
  - project_member: project-domain reads, comments R/C, attachments DL/C +
                    masters reads.
  - division_member: project reads + masters reads (very narrow tier).

The bootstrap user gets the super_admin role globally so they can grant
further roles (Doc-42b: only super_admin can grant SUPER_ADMIN).

Revision ID: u1a000000002
Revises: u1a000000001
Create Date: 2026-05-14
"""
from __future__ import annotations

import os
import uuid

import sqlalchemy as sa
from alembic import op
from argon2 import PasswordHasher

from app.core.permissions import (
    ADMIN_ROLE,
    ALL_MASTERS_READ_PERMISSIONS,
    ALL_PERMISSIONS,
    ALL_PROJECT_DOMAIN_PERMISSIONS,
    ALL_USER_FIELD_WRITES,
    ATTACHMENTS_CREATE,
    ATTACHMENTS_DOWNLOAD,
    COMMENTS_CREATE,
    COMMENTS_READ,
    DIVISION_MEMBER_ROLE,
    MILESTONES_READ,
    ORG_ADMIN_ROLE,
    PERMISSIONS_READ,
    PROJECT_ADMIN_ROLE,
    PROJECT_MEMBER_ROLE,
    PROJECT_MEMBER_WRITES,
    PROJECT_MEMBERS_READ,
    PROJECTS_READ,
    RBAC_ASSIGN,
    SUBTASKS_READ,
    SUPER_ADMIN_ROLE,
    TASKS_READ,
    USERS_DELETE_VENDOR,
    USERS_GRANT_SUPERADMIN,
    USERS_READ,
    USERS_READ_ALL,
)


revision = "u1a000000002"
down_revision = "u1a000000001"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Role → permission-set map (Doc-21B effective definition for each tier)
# ---------------------------------------------------------------------------

# --- Round-7 role bundles ---------------------------------------------------
# After the round-7 refactor, role-permission grants include the new
# field-level codes (`<r>:update:<f>`) as well as the action codes
# (create/read/delete/restore/publish/close/etc).
#
# super_admin: ALL_PERMISSIONS (incl. USERS_GRANT_SUPERADMIN).
# admin:       ALL_PERMISSIONS \ {USERS_GRANT_SUPERADMIN}.
# org_admin:   project-domain (all action + field codes) + user reads +
#              users:delete_vendor + RBAC assign + masters reads. ALWAYS
#              assigned at ("org", vendor_id) scope so the vendor->project
#              projection in RbacRepository hydrates project-scope perms.
# project_admin: project-domain (all action + field codes) + user reads +
#                masters reads. Assigned at ("project", project_id) scope.
# project_member: PROJECT_MEMBER_WRITES (status/priority/self-assign on
#                 tasks+subtasks, comments+attachments R/W) + standard reads.
#                 Assigned at ("project", project_id) scope.
# division_member: read-only across project + masters. Currently scope-agnostic.

# Round-8 H4: admin gets everything EXCEPT the SUPER_ADMIN-grant capability
# AND notification_templates:manage. The notification-template catalog
# stores email bodies for password-reset / OTP / account-lockout — putting
# this code on admin lets a compromised admin replace the password-reset
# email with a phishing link, which subverts the whole account-recovery
# flow. Restricted to super_admin only.
_ADMIN_EXCLUDE_CODES = frozenset({
    USERS_GRANT_SUPERADMIN,
    "notification_templates:manage",
})
_ADMIN_PERMS: tuple[str, ...] = tuple(
    p for p in ALL_PERMISSIONS if p not in _ADMIN_EXCLUDE_CODES
)

# org_admin and project_admin both wield the entire project-domain (action
# codes + field-level writes for projects/milestones/activities/tasks/subtasks).
_ORG_ADMIN_PERMS: tuple[str, ...] = (
    USERS_READ, USERS_READ_ALL, USERS_DELETE_VENDOR,
    PERMISSIONS_READ, RBAC_ASSIGN,
    *ALL_PROJECT_DOMAIN_PERMISSIONS,
    *ALL_MASTERS_READ_PERMISSIONS,
)

_PROJECT_ADMIN_PERMS: tuple[str, ...] = (
    USERS_READ,
    *ALL_PROJECT_DOMAIN_PERMISSIONS,
    *ALL_MASTERS_READ_PERMISSIONS,
)

# project_member: status/priority/assign on tasks+subtasks, comments R/C,
# attachments DL/C, plus standard reads. NO field-level writes on project /
# milestone / activity rows (those are admin-tier).
_PROJECT_MEMBER_PERMS: tuple[str, ...] = (
    USERS_READ,
    PROJECTS_READ,
    MILESTONES_READ, TASKS_READ, SUBTASKS_READ,
    *PROJECT_MEMBER_WRITES,
    PROJECT_MEMBERS_READ,
    *ALL_MASTERS_READ_PERMISSIONS,
)

# division_member: read-only observer tier.
_DIVISION_MEMBER_PERMS: tuple[str, ...] = (
    USERS_READ,
    PROJECTS_READ,
    MILESTONES_READ, TASKS_READ, SUBTASKS_READ,
    COMMENTS_READ, ATTACHMENTS_DOWNLOAD,
    *ALL_MASTERS_READ_PERMISSIONS,
)


_grants_by_role: dict[str, tuple[str, ...]] = {
    SUPER_ADMIN_ROLE: ALL_PERMISSIONS,
    ADMIN_ROLE: _ADMIN_PERMS,
    ORG_ADMIN_ROLE: _ORG_ADMIN_PERMS,
    PROJECT_ADMIN_ROLE: _PROJECT_ADMIN_PERMS,
    PROJECT_MEMBER_ROLE: _PROJECT_MEMBER_PERMS,
    DIVISION_MEMBER_ROLE: _DIVISION_MEMBER_PERMS,
}


_role_descriptions: dict[str, str] = {
    SUPER_ADMIN_ROLE: "Full PMIS admin including the ability to grant super_admin to other users.",
    ADMIN_ROLE: "Platform admin — full perms except granting super_admin.",
    ORG_ADMIN_ROLE: "Organization-scoped admin (manages vendor/org-tier projects + users).",
    PROJECT_ADMIN_ROLE: "Owns a single project end-to-end (R/W milestones, activities, members).",
    PROJECT_MEMBER_ROLE: "Day-to-day project participant (R/W on own work, masters read-only).",
    DIVISION_MEMBER_ROLE: "Division-scoped read-only observer.",
}


def upgrade() -> None:
    bind = op.get_bind()

    # ---------------------------------------------------------------- permissions
    perm_rows = [
        {"code": code, "name": code, "description": None, "is_builtin": True}
        for code in ALL_PERMISSIONS
    ]
    # Idempotent insert via raw SQL (op.bulk_insert is not ON-CONFLICT aware).
    if perm_rows:
        bind.execute(
            sa.text(
                "INSERT INTO users.permissions (code, name, description, is_builtin) "
                "VALUES (:code, :name, :description, :is_builtin) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            perm_rows,
        )

    # ---------------------------------------------------------------- roles
    for role_name, description in _role_descriptions.items():
        bind.execute(
            sa.text(
                "INSERT INTO users.roles (name, description, builtin) "
                "VALUES (:name, :description, true) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": role_name, "description": description},
        )

    # ---------------------------------------------------------------- role_permissions
    # Resolve role ids by name (post-insert) then bulk insert grants.
    role_id_by_name = {
        row[0]: row[1]
        for row in bind.execute(
            sa.text("SELECT name, id FROM users.roles WHERE name = ANY(:names)"),
            {"names": list(_grants_by_role.keys())},
        )
    }

    rp_rows: list[dict] = []
    for role_name, perms in _grants_by_role.items():
        role_id = role_id_by_name.get(role_name)
        if role_id is None:
            continue
        for code in perms:
            rp_rows.append({"role_id": role_id, "permission_code": code})

    if rp_rows:
        bind.execute(
            sa.text(
                "INSERT INTO users.role_permissions (role_id, permission_code) "
                "VALUES (:role_id, :permission_code) "
                "ON CONFLICT (role_id, permission_code) DO NOTHING"
            ),
            rp_rows,
        )

    # ---------------------------------------------------------------- bootstrap super_admin user
    # Q33: password sourced from env. If unset (e.g. CI / re-runs), skip user
    # creation but leave roles + perms in place.
    bootstrap_password = os.environ.get("SUPERADMIN_BOOTSTRAP_PASSWORD")
    bootstrap_login = os.environ.get("BOOTSTRAP_SUPERADMIN_LOGIN", "superadmin")
    bootstrap_email = os.environ.get(
        "BOOTSTRAP_SUPERADMIN_EMAIL", "superadmin@example.com"
    )

    if bootstrap_password:
        hashed = PasswordHasher().hash(bootstrap_password)
        bootstrap_user_id = str(uuid.uuid4())
        existing = bind.execute(
            sa.text("SELECT id FROM users.users WHERE login = :login"),
            {"login": bootstrap_login},
        ).first()
        if existing is None:
            bind.execute(
                sa.text(
                    "INSERT INTO users.users "
                    "(id, login, email, hashed_password, first_name, last_name, "
                    " status, two_factor_enabled) "
                    "VALUES (:id, :login, :email, :hashed, 'Bootstrap', 'Super-admin', "
                    " 'active', false)"
                ),
                {
                    "id": bootstrap_user_id,
                    "login": bootstrap_login,
                    "email": bootstrap_email,
                    "hashed": hashed,
                },
            )
        else:
            bootstrap_user_id = existing[0]

        super_admin_role_id = role_id_by_name.get(SUPER_ADMIN_ROLE)
        if super_admin_role_id is not None:
            bind.execute(
                sa.text(
                    "INSERT INTO users.user_roles (user_id, role_id) "
                    "VALUES (:user_id, :role_id) "
                    "ON CONFLICT (user_id, role_id) DO NOTHING"
                ),
                {"user_id": bootstrap_user_id, "role_id": super_admin_role_id},
            )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM users.user_roles"))
    bind.execute(sa.text("DELETE FROM users.users WHERE login IN ('superadmin')"))
    bind.execute(sa.text("DELETE FROM users.role_permissions"))
    bind.execute(
        sa.text("DELETE FROM users.roles WHERE name = ANY(:names)"),
        {"names": list(_grants_by_role.keys())},
    )
    bind.execute(
        sa.text("DELETE FROM users.permissions WHERE code = ANY(:codes)"),
        {"codes": list(ALL_PERMISSIONS)},
    )
