"""Backfill missing global role-assignment rows for users whose
``users.users.org_role`` column is set but who have no matching row in
``users.user_role_assignments`` at global scope.

Revision ID: r011_org_role_backfill
Revises: r010_add_director_division_roles
Create Date: 2026-06-02

NOTE: the revision id is intentionally kept short (≤32 chars). Alembic's
default ``alembic_version_users.version_num`` column is VARCHAR(32). A
previous attempt at this migration used the longer id
``r011_backfill_org_role_assignments`` (34 chars) — the migration body
ran fine on deploy, but the bookkeeping UPDATE to bump version_num
failed with ``StringDataRightTruncation``, rolling back the whole
transaction. Keep future revision ids ≤32 chars.

Context (CEO-class bug):

Before commit ``b7609ed``, ``user_service.create()`` accepted
``orgRole: "<role_name>"`` in the request and only wrote the value into
the legacy ``users.users.org_role`` varchar column. It did NOT create a
matching row in ``users.user_role_assignments``. Authorization reads
ONLY from ``user_role_assignments``, so these users had:

    users.users.org_role            = "director_admin"   (visible label)
    users.user_role_assignments     = no row              (zero codes)

Result: their login response showed a role, but every gated endpoint
returned 403. A real user (``login=CEO``) was discovered in this state
and was fixed manually as assignment_id=524 on 2026-06-02.

The create-flow itself is fixed in ``b7609ed`` (forward). This migration
fixes the existing data — any user already in the broken state gets the
missing global role-assignment inserted.

Behaviour:

  * Idempotent — uses ``ON CONFLICT (user_id, role_id, organization_id,
    project_id) DO NOTHING`` so re-running on an already-fixed DB does
    nothing.
  * Only inserts rows where the user's ``org_role`` column points to a
    BUILTIN role row (skips typos, ``test_role``, NULLs, empty strings).
  * Excludes soft-deleted users (``deleted_at IS NOT NULL``).
  * Excludes users who already have the matching role at global scope
    via EITHER ``user_role_assignments`` OR legacy ``user_roles``.
  * Backfilled rows carry ``created_by = NULL`` as a sentinel so the
    downgrade can identify and revoke only this migration's inserts.
  * Tagged with ``created_at = NOW()`` at upgrade time.

Per A19 (alembic conventions in PERMISSIONS_TEAM_DECISIONS.md §7.1),
real downgrade implemented. It removes only the rows this migration's
upgrade inserted — global rows with ``created_by IS NULL`` whose
(user_id, role_id) currently matches the user's ``org_role`` column.
Conservative; documented edge case in the downgrade docstring.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r011_org_role_backfill"
down_revision: str = "r010_add_director_division_roles"
branch_labels = None
depends_on = None


# Single INSERT-SELECT covers every CEO-class user in one statement.
# The LEFT JOINs ensure we don't re-insert when:
#   * the user already has a global user_role_assignments row for the role
#   * OR the user already holds the role via legacy user_roles
#
# Filters:
#   * org_role NOT NULL AND <> ''       — column actually set
#   * Role.builtin = TRUE               — only seed builtins (skip typos,
#                                          custom roles like 'test_role')
#   * user not soft-deleted             — leave deleted users alone
_BACKFILL_SQL = """
INSERT INTO users.user_role_assignments
    (user_id, role_id, organization_id, project_id, created_at, created_by)
SELECT u.id, r.id, NULL, NULL, NOW(), NULL
FROM   users.users u
JOIN   users.roles r
    ON r.name = u.org_role
   AND r.builtin = TRUE
LEFT JOIN users.user_role_assignments ura
    ON ura.user_id          = u.id
   AND ura.role_id          = r.id
   AND ura.organization_id  IS NULL
   AND ura.project_id       IS NULL
LEFT JOIN users.user_roles ur
    ON ur.user_id = u.id
   AND ur.role_id = r.id
WHERE  u.org_role        IS NOT NULL
  AND  u.org_role        <> ''
  AND  u.deleted_at      IS NULL
  AND  ura.id            IS NULL
  AND  ur.user_id        IS NULL
ON CONFLICT (user_id, role_id, organization_id, project_id) DO NOTHING
"""


# Downgrade SQL — removes only this migration's inserts. Identification
# rules (must ALL match):
#   * scope is global (organization_id IS NULL AND project_id IS NULL)
#   * created_by IS NULL (the sentinel set by upgrade)
#   * the user's CURRENT org_role column still points to this role's name
#
# Edge case: if an operator (or another migration) inserted a global
# role-assignment row with created_by IS NULL between this migration's
# upgrade and downgrade, AND that row's (user, role) happens to match
# the user's current org_role column, the downgrade will remove it too.
# That's intentionally accepted — no other practice should be producing
# NULL-created global rows.
_DOWNGRADE_SQL = """
DELETE FROM users.user_role_assignments ura
USING  users.users u, users.roles r
WHERE  ura.organization_id IS NULL
  AND  ura.project_id      IS NULL
  AND  ura.created_by      IS NULL
  AND  ura.user_id         = u.id
  AND  ura.role_id         = r.id
  AND  r.name              = u.org_role
"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(_BACKFILL_SQL))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(_DOWNGRADE_SQL))
