"""r024: restrict broad "read any user" to admin/super_admin.

Companion to the project_role_base fix. project_admin / project_member fuse
capability with project scope; their cross-cutting reads are now surfaced at
GLOBAL scope by the permission resolver (RbacRepository._project_base_reads,
keyed on the org_role column + permissions.PROJECT_ROLE_BASE_CODES), so a holder
with no project still holds them. That curated set deliberately EXCLUDES the
broad ``users:read_all`` (read any user record) — per policy that broad read
belongs to admin / super_admin only.

This migration revokes ``users:read_all`` from project_admin / project_member so
the role grants match that policy. No role/permission rows are created and no
data is backfilled — the base reads are computed live by the resolver from the
org_role column, so there is nothing to seed.
"""
from alembic import op


revision = "r024_project_role_base_grant"
down_revision = "r023_scope_org_admin_to_vendor"
branch_labels = None
depends_on = None


# Broad "read any user" stays admin/super_admin only.
_UP_STRIP_READ_ALL = """
DELETE FROM users.role_permissions rp
USING users.roles r
WHERE rp.role_id = r.id
  AND r.name IN ('project_admin', 'project_member')
  AND rp.permission_code = 'users:read_all';
"""

# Reverse: restore the grant (only if the permission code still exists).
_DOWN_RESTORE_READ_ALL = """
INSERT INTO users.role_permissions (role_id, permission_code)
SELECT r.id, 'users:read_all'
FROM users.roles r
WHERE r.name IN ('project_admin', 'project_member')
  AND EXISTS (SELECT 1 FROM users.permissions p WHERE p.code = 'users:read_all')
ON CONFLICT (role_id, permission_code) DO NOTHING;
"""


def upgrade() -> None:
    op.execute(_UP_STRIP_READ_ALL)


def downgrade() -> None:
    op.execute(_DOWN_RESTORE_READ_ALL)
