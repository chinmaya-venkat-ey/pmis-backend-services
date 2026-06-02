"""Cleanup: delete r001 orphans + revoke grants for deleted dead-canonical codes.

Revision ID: r007_orphan_and_deadcode_cleanup
Revises: r006_revoke_grant_superadmin
Create Date: 2026-06-02

Bundled cleanups (per permissions_decisions.md decisions A8, A16, A17 grants, A18):

  1. A16 / A18 — Delete the 16 r001 orphan permission codes from
     users.permissions and any role_permissions rows referencing them.
     These codes were inserted by r001_reseed_role_permissions.py but
     never enforced anywhere; they exist as DB noise only. Several were
     naming-divergent twins of canonical codes (`attachments:upload` vs
     `attachments:create`, `*:depends_on` vs `*:dependencies`,
     `*:resource_mode` vs `*:resource`).

  2. A17 grants — Delete the 5 dead canonical codes that the Phase 3
     code cleanup already removed from app/core/permissions.py:
       - projects:draft
       - project_members:add
       - project_members:delete
       - attachments:download
       - attachments:delete
     Their role_permissions rows are revoked here and the rows are
     removed from users.permissions. Keep COMMENTS_MODERATE pending the
     B3 team decision.

  3. A8 — Revoke `attachments:delete` from project_member (r001 added
     this grant; u1a's intent did not include it). Subsumed by step 2
     above since the code itself is being removed from the catalog.

  All operations are scoped to specific code strings. DELETE is
  idempotent for missing rows.

  Per A19, real downgrade implemented.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r007_orphan_and_deadcode_cleanup"
down_revision: str = "r006_revoke_grant_superadmin"
branch_labels = None
depends_on = None


_R001_ORPHANS = (
    "projects:save",
    "projects:update:status",
    "projects:update:active",
    "projects:update:category",
    "projects:update:parent_id",
    "milestones:update:depends_on",
    "activities:update:resource_mode",
    "activities:update:type",
    "tasks:update:resource_mode",
    "tasks:update:resource_count",
    "tasks:update:type",
    "subtasks:update:resource_mode",
    "subtasks:update:resource_count",
    "subtasks:update:type",
    "comments:delete",
    "attachments:upload",
)

_DEAD_CANONICAL = (
    "projects:draft",
    "project_members:add",
    "project_members:delete",
    "attachments:download",
    "attachments:delete",
)


def upgrade() -> None:
    bind = op.get_bind()

    all_codes_to_delete = list(_R001_ORPHANS) + list(_DEAD_CANONICAL)

    bind.execute(sa.text("""
        DELETE FROM users.role_permissions
        WHERE permission_code = ANY(:codes)
    """), {"codes": all_codes_to_delete})

    bind.execute(sa.text("""
        DELETE FROM users.user_permissions
        WHERE permission_code = ANY(:codes)
    """), {"codes": all_codes_to_delete})

    bind.execute(sa.text("""
        DELETE FROM users.permissions
        WHERE code = ANY(:codes)
    """), {"codes": all_codes_to_delete})


def downgrade() -> None:
    """Recreate the deleted permission rows and restore the grant pattern
    that existed before this migration.

    For the 16 r001 orphans: restore u1a/r001/r002 grant pattern.
    For the 5 dead canonical codes: restore u1a/r002 grant pattern.

    Idempotent via ON CONFLICT.
    """
    bind = op.get_bind()

    all_codes = list(_R001_ORPHANS) + list(_DEAD_CANONICAL)

    for code in all_codes:
        bind.execute(sa.text("""
            INSERT INTO users.permissions (code, name, description, is_builtin)
            VALUES (:code, :code, :code, true)
            ON CONFLICT (code) DO NOTHING
        """), {"code": code})

    role_rows = bind.execute(sa.text(
        "SELECT name, id FROM users.roles "
        "WHERE name IN ('super_admin', 'admin', 'org_admin', 'project_admin', 'project_member')"
    )).fetchall()
    role_id_by_name = {n: i for n, i in role_rows}

    for role_name in ("super_admin", "admin"):
        rid = role_id_by_name.get(role_name)
        if rid is None:
            continue
        for code in all_codes:
            bind.execute(sa.text("""
                INSERT INTO users.role_permissions (role_id, permission_code)
                VALUES (:rid, :code)
                ON CONFLICT (role_id, permission_code) DO NOTHING
            """), {"rid": rid, "code": code})

    for role_name in ("org_admin", "project_admin"):
        rid = role_id_by_name.get(role_name)
        if rid is None:
            continue
        for code in _DEAD_CANONICAL:
            bind.execute(sa.text("""
                INSERT INTO users.role_permissions (role_id, permission_code)
                VALUES (:rid, :code)
                ON CONFLICT (role_id, permission_code) DO NOTHING
            """), {"rid": rid, "code": code})

    pm_rid = role_id_by_name.get("project_member")
    if pm_rid is not None:
        for code in ("attachments:download",):
            bind.execute(sa.text("""
                INSERT INTO users.role_permissions (role_id, permission_code)
                VALUES (:rid, :code)
                ON CONFLICT (role_id, permission_code) DO NOTHING
            """), {"rid": pm_rid, "code": code})

        for code in ("comments:delete", "attachments:upload", "attachments:delete"):
            bind.execute(sa.text("""
                INSERT INTO users.role_permissions (role_id, permission_code)
                VALUES (:rid, :code)
                ON CONFLICT (role_id, permission_code) DO NOTHING
            """), {"rid": pm_rid, "code": code})
