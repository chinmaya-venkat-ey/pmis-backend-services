"""Purge all sla_quarterly_aggregate rows so they regenerate under the new
resource-phase anchor.

The SLA quarter anchor moved from the project start to the resource-based phase
start (earliest resource-based milestone) — ``app/utilities/project_anchor.py``.
Every existing aggregate was bucketed/labelled on the OLD (project-start) anchor,
so its ``(fiscal_year, quarter)`` label no longer matches the same quarter under
the new anchor (e.g. a project's Apr–Jul quarter was ``Y2-Q3`` on the project
anchor, and is ``Y1-Q2`` on the phase anchor). Leaving them would strand stale,
mislabelled rows alongside the freshly-rolled ones.

``sla_quarterly_aggregate`` is DERIVED (summed from ``sla_evaluation_results`` by
``rollup_mapping_for_quarter``) and is regenerated on the next quarterly-aggregate
GET / settlement close, so deleting every row is safe — the rows rebuild under the
new anchor on next access. Settlements (``sla_settlement_period``) are NOT touched
here; re-close them with ``GET .../settlement?refresh=true`` after deploy so they
recompute against the regenerated aggregates (invoiced/overridden stay frozen).

Downgrade is an intentional no-op — the deleted rows are derived and rebuild on
read; there is nothing correct to restore. Mirrors 0031/0035/0036/0037.

Revision ID: 0038_purge_aggs_reanchor
Revises:     0037_purge_calendar_aggs
Create Date: 2026-08-17
"""
from __future__ import annotations

from alembic import op


revision = "0038_purge_aggs_reanchor"
down_revision = "0037_purge_calendar_aggs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Derived rows — regenerated on next rollup/settlement read under the new anchor.
    op.execute("DELETE FROM contract.sla_quarterly_aggregate")


def downgrade() -> None:
    # Intentional no-op — aggregates are derived and rebuild on read.
    pass
