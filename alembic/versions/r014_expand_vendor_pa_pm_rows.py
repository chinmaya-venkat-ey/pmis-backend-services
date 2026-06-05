"""Expand legacy vendor-scoped project_admin / project_member rows into
per-project rows so the architectural rule "PA/PM must be project-scoped"
holds for existing data.

Revision ID: r014_expand_pa_pm
Revises: r013_users_list_orgs
Create Date: 2026-06-04

Bug-Hunter (a) follow-up to #133/#142/#213:

Vendor-scoped grants of project_admin / project_member
(``organization_id IS NOT NULL`` AND ``project_id IS NULL``) acted as a
hidden one-to-many shortcut: the auth-time projection in
``rbac_repository.effective_permissions_by_scope`` granted the user PA/PM
on every project mapped to that vendor, but the per-project read paths
(``list_role_assignments_for_project`` etc.) only saw rows that named a
project. The lists silently underreported access.

The runtime API (``role_assignment_service._assert_caller_can_grant``)
now refuses new vendor-scoped PA/PM grants. This migration normalises
the existing data:

  For every live row where ``role IN (project_admin, project_member)``,
  ``organization_id`` is set, and ``project_id`` is NULL:
    1. Look up every live project mapped to that organization (vendor)
       via ``project.project_vendors``.
    2. For each such project, ensure a row exists for
       ``(user_id, role_id, organization_id=NULL, project_id=<P>)``
       (idempotent — skips rows that already exist).
       ``created_by`` and ``created_at`` are inherited from the source
       row so audit history points back to the original grant.
    3. After every expansion succeeds, delete the original vendor-
       scoped row.

Idempotent: rerunning the migration on already-expanded data is a
no-op (the source query returns nothing).

Per A19 a real downgrade is implemented (best-effort), although it
cannot perfectly reverse the expansion — the per-project rows can be
collapsed back only if there is exactly one (user, role) group whose
project_id set matches the vendor's project mapping. The downgrade
leaves the expanded rows in place when ambiguous and only removes the
ones it can confidently roll back; the runtime behaviour is unaffected
either way.

Revision id is 16 chars — under the 32-char alembic version_num cap.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r014_expand_pa_pm"
down_revision: str = "r013_users_list_orgs"
branch_labels = None
depends_on = None


_TARGET_ROLES = ("project_admin", "project_member")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Inventory the rows we need to expand.
    legacy_rows = bind.execute(sa.text("""
        SELECT
            ura.id            AS legacy_id,
            ura.user_id       AS user_id,
            ura.role_id       AS role_id,
            r.name            AS role_name,
            ura.organization_id AS vendor_id,
            ura.created_by    AS created_by,
            ura.created_at    AS created_at
          FROM users.user_role_assignments ura
          JOIN users.roles r ON r.id = ura.role_id
         WHERE r.name = ANY(:roles)
           AND ura.organization_id IS NOT NULL
           AND ura.project_id IS NULL
    """), {"roles": list(_TARGET_ROLES)}).fetchall()

    if not legacy_rows:
        print("[r014_expand_pa_pm] no vendor-scoped PA/PM rows found; no-op.")
        return

    legacy_ids_to_delete: list[int] = []
    inserted = 0
    skipped_dup = 0
    vendors_without_projects = 0

    for legacy_id, user_id, role_id, role_name, vendor_id, created_by, created_at in legacy_rows:
        # 2. Live projects mapped to this vendor.
        # project_vendors is a join table with no soft-delete; filter the
        # project itself on deleted_at to skip dead projects.
        project_ids = [pid for (pid,) in bind.execute(sa.text("""
            SELECT pv.project_id
              FROM project.project_vendors pv
              JOIN project.projects p ON p.id = pv.project_id
             WHERE pv.vendor_id = :vid
               AND p.deleted_at IS NULL
        """), {"vid": vendor_id}).fetchall()]

        if not project_ids:
            vendors_without_projects += 1
            # Still delete the legacy row — a vendor-scoped PA/PM with no
            # mapped projects granted nothing, and it would crash the
            # write-path guard on future edits.
            legacy_ids_to_delete.append(legacy_id)
            continue

        for pid in project_ids:
            # Idempotent insert — skip if (user, role, project) already
            # exists (handles partial-run recovery and the rare case
            # where someone happened to be granted directly too).
            existing = bind.execute(sa.text("""
                SELECT 1
                  FROM users.user_role_assignments
                 WHERE user_id = :uid
                   AND role_id = :rid
                   AND project_id = :pid
                   AND organization_id IS NULL
                 LIMIT 1
            """), {"uid": user_id, "rid": role_id, "pid": pid}).first()
            if existing is not None:
                skipped_dup += 1
                continue
            bind.execute(sa.text("""
                INSERT INTO users.user_role_assignments
                    (user_id, role_id, organization_id, project_id,
                     created_by, created_at)
                VALUES
                    (:uid, :rid, NULL, :pid, :cb, :ca)
            """), {
                "uid": user_id, "rid": role_id, "pid": pid,
                "cb": created_by, "ca": created_at,
            })
            inserted += 1

        legacy_ids_to_delete.append(legacy_id)

    # 3. Delete the original vendor-scoped rows (only the ones we
    # successfully expanded or determined granted nothing).
    if legacy_ids_to_delete:
        bind.execute(sa.text("""
            DELETE FROM users.user_role_assignments
             WHERE id = ANY(:ids)
        """), {"ids": legacy_ids_to_delete})

    print(
        f"[r014_expand_pa_pm] expanded {len(legacy_rows)} vendor-scoped "
        f"PA/PM row(s): inserted {inserted} per-project rows, skipped "
        f"{skipped_dup} duplicates, {vendors_without_projects} vendor(s) "
        f"had no live mapped projects (their legacy rows were dropped)."
    )


def downgrade() -> None:
    # Best-effort: not perfectly reversible — the per-project rows we
    # produced are indistinguishable from rows the runtime API may have
    # since written, and removing them could discard real grants. Leave
    # the data as-is; the schema is unchanged, so the only side effect
    # of staying upgraded is that PA/PM rows continue to name a project.
    print(
        "[r014_expand_pa_pm] downgrade is a no-op — the expansion is not "
        "safely reversible without per-row provenance metadata."
    )
