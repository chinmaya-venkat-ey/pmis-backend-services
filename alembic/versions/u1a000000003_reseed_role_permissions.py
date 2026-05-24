"""Reseed role_permissions for org_admin / project_admin / project_member.

Revision ID: u1a000000003
Revises: u1a000000002
Create Date: 2026-05-24

Bug #13: org_admin and project_admin could not view User/Org Management
pages because required permission codes were missing from role_permissions
in the deployed DB (monolith used different codes). Idempotent - safe to
re-run.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "u1a000000003"
down_revision: str = "u1a000000002"
branch_labels = None
depends_on = None

_ALL_MASTERS_READ = (
    "divisions:read", "vendors:read", "resource_types:read",
    "priorities:read", "project_categories:read",
    "activity_types:read", "activity_statuses:read", "milestone_statuses:read",
)

_ALL_PROJECT_DOMAIN = (
    "projects:read", "projects:read_all", "projects:create",
    "projects:publish", "projects:close", "projects:save",
    "projects:update:name", "projects:update:description",
    "projects:update:start_date", "projects:update:end_date",
    "projects:update:status", "projects:update:active",
    "projects:update:public", "projects:update:owner",
    "projects:update:category", "projects:update:vendors",
    "projects:update:parent_id",
    "milestones:read", "milestones:create", "milestones:delete",
    "milestones:restore",
    "milestones:update:name", "milestones:update:description",
    "milestones:update:start_date", "milestones:update:end_date",
    "milestones:update:actual_start_date", "milestones:update:actual_end_date",
    "milestones:update:status", "milestones:update:priority",
    "milestones:update:position", "milestones:update:depends_on",
    "milestones:update:vendors",
    "activities:read", "activities:create", "activities:delete",
    "activities:restore",
    "activities:update:name", "activities:update:description",
    "activities:update:start_date", "activities:update:end_date",
    "activities:update:actual_start_date", "activities:update:actual_end_date",
    "activities:update:status", "activities:update:priority",
    "activities:update:position", "activities:update:vendor_id",
    "activities:update:owner_division", "activities:update:concerned_divisions",
    "activities:update:resource_mode", "activities:update:type",
    "tasks:read", "tasks:create", "tasks:delete", "tasks:restore",
    "tasks:update:name", "tasks:update:description",
    "tasks:update:start_date", "tasks:update:end_date",
    "tasks:update:actual_start_date", "tasks:update:actual_end_date",
    "tasks:update:status", "tasks:update:priority",
    "tasks:update:position", "tasks:update:assigned_to",
    "tasks:update:resource_mode", "tasks:update:resource_count",
    "tasks:update:type",
    "subtasks:read", "subtasks:create", "subtasks:delete", "subtasks:restore",
    "subtasks:update:name", "subtasks:update:description",
    "subtasks:update:start_date", "subtasks:update:end_date",
    "subtasks:update:actual_start_date", "subtasks:update:actual_end_date",
    "subtasks:update:status", "subtasks:update:priority",
    "subtasks:update:position", "subtasks:update:assigned_to",
    "subtasks:update:resource_mode", "subtasks:update:resource_count",
    "subtasks:update:type",
    "comments:read", "comments:create", "comments:delete",
    "attachments:upload", "attachments:download", "attachments:delete",
    "project_members:read", "project_members:add",
    "project_members:update", "project_members:delete",
)

_PROJECT_MEMBER_WRITES = (
    "tasks:update:status", "tasks:update:priority", "tasks:update:assigned_to",
    "subtasks:update:status", "subtasks:update:priority",
    "subtasks:update:assigned_to",
    "comments:create", "comments:delete",
    "attachments:upload", "attachments:download", "attachments:delete",
)

_ORG_ADMIN_PERMS = (
    "users:read", "users:read_all", "users:delete_vendor",
    "permissions:read", "rbac:assign",
    *_ALL_PROJECT_DOMAIN,
    *_ALL_MASTERS_READ,
)

_PROJECT_ADMIN_PERMS = (
    "users:read",
    *_ALL_PROJECT_DOMAIN,
    *_ALL_MASTERS_READ,
)

_PROJECT_MEMBER_PERMS = (
    "users:read", "projects:read",
    "milestones:read", "tasks:read", "subtasks:read",
    *_PROJECT_MEMBER_WRITES,
    "project_members:read",
    *_ALL_MASTERS_READ,
)

_DIVISION_MEMBER_PERMS = (
    "users:read", "projects:read",
    "milestones:read", "tasks:read", "subtasks:read",
    "comments:read", "attachments:download",
    *_ALL_MASTERS_READ,
)

_GRANTS_BY_ROLE = {
    "org_admin": _ORG_ADMIN_PERMS,
    "project_admin": _PROJECT_ADMIN_PERMS,
    "project_member": _PROJECT_MEMBER_PERMS,
    "division_member": _DIVISION_MEMBER_PERMS,
}

_ALL_CODES_NEEDED = set()
for _perms in _GRANTS_BY_ROLE.values():
    _ALL_CODES_NEEDED.update(_perms)


def upgrade() -> None:
    bind = op.get_bind()
    for code in sorted(_ALL_CODES_NEEDED):
        bind.execute(
            sa.text(
                "INSERT INTO users.permissions (code, name, description, is_builtin) "
                "VALUES (:code, :name, :description, true) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": code, "description": code},
        )
    role_rows = bind.execute(
        sa.text("SELECT name, id FROM users.roles WHERE name = ANY(:names)"),
        {"names": list(_GRANTS_BY_ROLE.keys())},
    ).fetchall()
    role_id_by_name = {name: rid for name, rid in role_rows}
    for role_name, perms in _GRANTS_BY_ROLE.items():
        rid = role_id_by_name.get(role_name)
        if rid is None:
            continue
        for code in set(perms):
            bind.execute(
                sa.text(
                    "INSERT INTO users.role_permissions "
                    "(role_id, permission_code) "
                    "VALUES (:role_id, :permission_code) "
                    "ON CONFLICT (role_id, permission_code) DO NOTHING"
                ),
                {"role_id": rid, "permission_code": code},
            )


def downgrade() -> None:
    pass
