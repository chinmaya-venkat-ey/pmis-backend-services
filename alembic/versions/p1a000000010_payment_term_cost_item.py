"""Add cost_item_id to project_payment_terms (row-based payment calculations).

Revision ID: p1a000000010
Revises: p1a000000009
Create Date: 2026-06-04

Why:
  Payment calculations move from PHASE-based to COST-ROW-based: a payment
  term's value is ``percent × its cost row's total`` and the 100% cap applies
  per cost row (not per phase). Each payment term therefore needs to know its
  cost row. ``cost_item_id`` denormalizes that link (a milestone is in exactly
  one live cost row, so it is well-defined); it is set by the cost-item
  reconcile going forward and back-filled here for existing live rows.

  ``phase`` is retained purely as a display grouping. Nullable + additive —
  existing rows keep working.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000010"
down_revision: str = "p1a000000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_payment_terms",
        sa.Column(
            "cost_item_id", sa.String(36),
            sa.ForeignKey("project.project_cost_items.id"), nullable=True,
        ),
        schema="project",
    )
    op.create_index(
        "ix_payment_terms_cost_item_id", "project_payment_terms", ["cost_item_id"],
        schema="project",
    )

    # Backfill existing live payment terms from the cost_item_milestones binding
    # (milestone -> live cost row). Idempotent; only fills NULLs.
    op.execute(
        sa.text("""
        UPDATE project.project_payment_terms AS pt
        SET cost_item_id = cim.cost_item_id
        FROM project.cost_item_milestones AS cim
        JOIN project.project_cost_items AS ci
          ON ci.id = cim.cost_item_id AND ci.deleted_at IS NULL
        WHERE cim.milestone_id = pt.milestone_id
          AND pt.deleted_at IS NULL
          AND pt.cost_item_id IS NULL
        """)
    )


def downgrade() -> None:
    op.drop_index("ix_payment_terms_cost_item_id", table_name="project_payment_terms", schema="project")
    op.drop_column("project_payment_terms", "cost_item_id", schema="project")
