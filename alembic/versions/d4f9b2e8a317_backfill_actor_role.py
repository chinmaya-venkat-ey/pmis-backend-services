"""Backfill actor_role on project_audit_logs with real role buckets.

Revision ID: d4f9b2e8a317
Revises: c3a8d1f7e542
Create Date: 2026-05-12

Mirror of monolith migration d4f9b2e8a317.

The original doc-47 migration (b1d3e7a9c204) set ``actor_role='system'``
on every legacy row because we didn't have the join logic in place yet.
Now we do — this migration rewrites those ``'system'`` rows (where the
actor is a real user) using the same highest-tier-wins resolution that
``record_audit`` does for new rows.

Resolution order, per row:
  1) Highest tier in ('super_admin','admin','org_admin','project_admin',
     'project_member','division_member') appearing in user_role_assignments.
  2) users.org_role column (round 9b).
  3) 'user' — authenticated but no role grant on file.
  4) 'system' — actor_id IS NULL.

Rows whose actor_id points to a now-deleted user fall through to 'user'.

Idempotent: re-running on a row already at 'admin' (etc.) is a no-op
because the WHERE clause only touches rows where actor_role='system'
AND the resolver finds a better tier.
"""
from alembic import op


revision = "d4f9b2e8a317"
down_revision = "c3a8d1f7e542"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tiered backfill — apply in priority order, only overwriting 'system'.
    # Each statement updates audit rows where the actor has a matching role
    # in user_role_assignments AND the current value is still 'system'.
    tier_sqls = [
        ("super_admin",
         "UPDATE project_audit_logs SET actor_role = 'super_admin' "
         "WHERE actor_role = 'system' AND actor_id IS NOT NULL AND EXISTS ("
         "    SELECT 1 FROM user_role_assignments ura "
         "    JOIN roles r ON r.id = ura.role_id "
         "    WHERE ura.user_id = project_audit_logs.actor_id "
         "      AND r.name = 'super_admin')"),
        ("admin",
         "UPDATE project_audit_logs SET actor_role = 'admin' "
         "WHERE actor_role = 'system' AND actor_id IS NOT NULL AND EXISTS ("
         "    SELECT 1 FROM user_role_assignments ura "
         "    JOIN roles r ON r.id = ura.role_id "
         "    WHERE ura.user_id = project_audit_logs.actor_id "
         "      AND r.name = 'admin')"),
        ("org_admin",
         "UPDATE project_audit_logs SET actor_role = 'org_admin' "
         "WHERE actor_role = 'system' AND actor_id IS NOT NULL AND EXISTS ("
         "    SELECT 1 FROM user_role_assignments ura "
         "    JOIN roles r ON r.id = ura.role_id "
         "    WHERE ura.user_id = project_audit_logs.actor_id "
         "      AND r.name = 'org_admin')"),
        ("project_admin",
         "UPDATE project_audit_logs SET actor_role = 'project_admin' "
         "WHERE actor_role = 'system' AND actor_id IS NOT NULL AND EXISTS ("
         "    SELECT 1 FROM user_role_assignments ura "
         "    JOIN roles r ON r.id = ura.role_id "
         "    WHERE ura.user_id = project_audit_logs.actor_id "
         "      AND r.name = 'project_admin')"),
        ("project_member",
         "UPDATE project_audit_logs SET actor_role = 'project_member' "
         "WHERE actor_role = 'system' AND actor_id IS NOT NULL AND EXISTS ("
         "    SELECT 1 FROM user_role_assignments ura "
         "    JOIN roles r ON r.id = ura.role_id "
         "    WHERE ura.user_id = project_audit_logs.actor_id "
         "      AND r.name = 'project_member')"),
        ("division_member",
         "UPDATE project_audit_logs SET actor_role = 'division_member' "
         "WHERE actor_role = 'system' AND actor_id IS NOT NULL AND EXISTS ("
         "    SELECT 1 FROM user_role_assignments ura "
         "    JOIN roles r ON r.id = ura.role_id "
         "    WHERE ura.user_id = project_audit_logs.actor_id "
         "      AND r.name = 'division_member')"),
    ]
    for _, sql in tier_sqls:
        op.execute(sql)

    # Tier 2 fallback: users.org_role column (round 9b) for any rows
    # whose actor has the column populated even though they have no
    # user_role_assignments row.
    op.execute(
        "UPDATE project_audit_logs "
        "SET actor_role = users.org_role "
        "FROM users "
        "WHERE project_audit_logs.actor_id = users.id "
        "  AND project_audit_logs.actor_role = 'system' "
        "  AND users.org_role IS NOT NULL "
        "  AND users.org_role IN ('super_admin','admin','org_admin',"
        "'project_admin','project_member','division_member')"
    )

    # Tier 3 fallback: authenticated user with no detectable role bucket.
    # Reclassify as 'user' to distinguish from real system actions.
    op.execute(
        "UPDATE project_audit_logs SET actor_role = 'user' "
        "WHERE actor_role = 'system' AND actor_id IS NOT NULL"
    )

    # actor_role for rows where actor_id IS NULL stays 'system' — correct.


def downgrade() -> None:
    # No-op: this migration overwrote denormalized snapshot values
    # that we can't reconstruct. Downgrading would require restoring
    # the prior 'system'-everywhere state, which is a regression
    # rather than a rollback. Intentional empty downgrade.
    pass
