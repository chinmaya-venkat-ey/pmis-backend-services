"""Priorities cleanup: enforce P1/P2/P3 only, sync labels to codes.

Revision ID: m1a000000003_priorities_cleanup
Revises: m1a000000002
Create Date: 2026-05-25

Why:
  The deployed catalog had drifted to 5 priority rows: P1 (name='High'),
  P2 (name='Medium'), P3 (name='Low'), plus two non-builtin stragglers
  FINALTEST (name='Updated') and QA_PRIO (name='QA Priority Updated').
  Product decision: priorities should be exactly P1, P2, P3 with name
  matching the code (no High/Medium/Low labels). Non-builtin priorities
  should be removed; any existing M/A/T/S row that referenced one is
  remapped to P3 so dependent records aren't broken.

  Idempotent (uses ON CONFLICT-style guards) — safe to rerun.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "m1a000000003_priorities_cleanup"
down_revision: str = "m1a000000002"
branch_labels = None
depends_on = None


_CANONICAL_PRIORITIES = ("P1", "P2", "P3")
_FALLBACK_CODE = "P3"  # safest remap target — least urgent


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Sync name to code for canonical priorities.
    for code in _CANONICAL_PRIORITIES:
        bind.execute(
            sa.text(
                "UPDATE masters.priorities SET name = :code "
                "WHERE code = :code AND name <> :code"
            ),
            {"code": code},
        )

    # 2. Find stragglers (non-canonical priorities).
    stragglers = [
        row[0] for row in bind.execute(sa.text(
            "SELECT code FROM masters.priorities "
            "WHERE code NOT IN :canonical"
        ), {"canonical": _CANONICAL_PRIORITIES}).all()
    ]

    if not stragglers:
        return

    # 3. Remap references in project.* tables. Each entity stores priority
    # by code (string), so a simple UPDATE works. Schemas are dependent on
    # the project schema existing — guard with information_schema lookup
    # so this migration is safe to run on a master-only env.
    project_schema_exists = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.schemata "
        "WHERE schema_name = 'project')"
    )).scalar()

    if project_schema_exists:
        for table in ("milestones", "activities", "tasks", "subtasks"):
            bind.execute(
                sa.text(
                    f"UPDATE project.{table} SET priority = :fallback "
                    f"WHERE priority = ANY(:stragglers)"
                ),
                {"fallback": _FALLBACK_CODE, "stragglers": stragglers},
            )

    # 4. Delete the straggler rows from the catalog.
    bind.execute(
        sa.text("DELETE FROM masters.priorities WHERE code = ANY(:codes)"),
        {"codes": stragglers},
    )


def downgrade() -> None:
    # Intentional no-op: recreating arbitrary straggler rows + restoring
    # name='High'/'Medium'/'Low' would re-introduce the data drift this
    # migration cleans up. If a rollback is needed, do it via a follow-up
    # forward migration.
    pass
