"""r023: scope existing org_admin role assignments to the user's vendor.

#246 / #254. Org-tier roles (org_admin) move from GLOBAL
(``organization_id IS NULL``) to VENDOR-scoped
(``organization_id = the user's vendor_id``). Once scoped, their permissions
resolve under the ``("org", vendor)`` bucket instead of the flat/global set,
the Round-7 vendor->project projection limits them to that vendor's projects
(fixes #246 properly), and ``/authz/users?vendor_id=V&role=org_admin`` can
discover them (fixes the #254 picker).

Vendor-less org_admins (no ``users.vendor_id``) are left GLOBAL — there is
nothing to scope them to; the runtime now rejects creating new ones, and any
legacy rows should be given a vendor and re-run.
"""
from alembic import op


revision = "r023_scope_org_admin_to_vendor"
down_revision = "r022_refresh_tokens_table"
branch_labels = None
depends_on = None


_UP = """
UPDATE users.user_role_assignments ra
SET organization_id = u.vendor_id
FROM users.users u, users.roles r
WHERE ra.user_id = u.id
  AND ra.role_id = r.id
  AND r.name = 'org_admin'
  AND ra.organization_id IS NULL
  AND ra.project_id IS NULL
  AND u.vendor_id IS NOT NULL;
"""

# Reverse: collapse org_admin org-tier rows back to GLOBAL (organization_id NULL).
_DOWN = """
UPDATE users.user_role_assignments ra
SET organization_id = NULL
FROM users.roles r
WHERE ra.role_id = r.id
  AND r.name = 'org_admin'
  AND ra.project_id IS NULL;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
