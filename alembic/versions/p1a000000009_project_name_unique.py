"""Enforce project-name uniqueness via partial unique index.

Revision ID: p1a000000009
Revises: p1a000000008
Create Date: 2026-06-04

Bug #141: "[PROJECT MANAGEMENT] The Project Name must be unique for every
single project". Adds a partial UNIQUE index on ``project.projects.name``
restricted to live rows (``deleted_at IS NULL``). Soft-deleted projects
free their name so it can be reused — matches the soft-delete semantics
of other uniqueness invariants in the schema.

Pre-existing duplicates:
  Any live rows that share a name are reconciled BEFORE the index is
  created: the OLDEST row in each duplicate group (ordered by
  ``created_at ASC``, tie-broken by ``id ASC``) is kept; every other
  live row in the group is **soft-deleted** by setting ``deleted_at =
  now()``. ``deleted_by`` stays NULL (system action; no user). Child
  rows (milestones / activities / cost items / etc.) are NOT cascaded —
  the soft-deleted parent makes them unreachable via the standard
  project reads, which is sufficient for the uniqueness goal. The
  dedupe is idempotent: re-running the migration on a DB with no
  duplicates is a no-op.

Index:
  * ``uq_projects_name_live`` — partial UNIQUE on ``name`` where
    ``deleted_at IS NULL``. Service-side pre-checks surface a friendly
    409 ConflictError before this fires; the index is the race-safe
    safety net.

Per A19 a real downgrade is implemented: drop the index. The downgrade
does NOT restore the dedupe'd rows (deliberate — re-introducing the
duplicates would immediately conflict with any subsequent re-application
of the index, and the dedupe action is auditable from the deploy log).

Revision id is intentionally short (12 chars) to comfortably fit under
the 32-char ``version_num`` column.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision: str = "p1a000000009"
down_revision: str = "p1a000000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Inventory of duplicate groups before action — drives the deploy-log
    # NOTICE so the action is auditable.
    dupe_groups = bind.execute(text(
        "SELECT name, COUNT(*) AS n FROM project.projects "
        "WHERE deleted_at IS NULL GROUP BY name HAVING COUNT(*) > 1 "
        "ORDER BY n DESC, name"
    )).fetchall()

    if dupe_groups:
        sample = ", ".join(f"{n!r}x{c}" for n, c in dupe_groups[:10])
        # Soft-delete every live duplicate except the OLDEST in each
        # group (created_at ASC, id ASC). deleted_by stays NULL — this is
        # a system action with no user actor. updated_at is bumped so the
        # row's modification timestamp reflects this change.
        result = bind.execute(text("""
            UPDATE project.projects
               SET deleted_at = now(),
                   updated_at = now()
             WHERE deleted_at IS NULL
               AND id NOT IN (
                   SELECT DISTINCT ON (name) id
                     FROM project.projects
                    WHERE deleted_at IS NULL
                    ORDER BY name, created_at ASC, id ASC
               )
        """))
        print(
            f"[p1a000000009] soft-deleted {result.rowcount} duplicate "
            f"project row(s) across {len(dupe_groups)} name-group(s); "
            f"kept oldest per name. Sample: {sample}"
        )

    op.execute(
        "CREATE UNIQUE INDEX uq_projects_name_live "
        "ON project.projects (name) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    # The dedupe is NOT reversed — see module docstring.
    op.execute("DROP INDEX IF EXISTS project.uq_projects_name_live")
