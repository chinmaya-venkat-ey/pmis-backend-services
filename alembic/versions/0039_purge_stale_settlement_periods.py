"""Purge non-frozen settlement periods so they regenerate under the phase anchor.

The SLA quarter anchor moved from the project start to the resource-based phase
start (0038 + ``app/utilities/project_anchor.py``). ``sla_quarterly_aggregate``
was purged by 0038 and rebuilds on read, but ``sla_settlement_period`` rows were
NOT — and those carry a stored ``(fiscal_year, quarter, quarter_start,
quarter_end)`` bucketed under the OLD anchor (project-start, or an even older
calendar generation). Under the new anchor those labels no longer map to the
project's real phase quarters, so a project accumulates duplicate / mislabelled
rows that double-count F (e.g. the same quarter's payment under both a calendar
``Y2-Q2`` and the phase ``Y1-Q2``).

This deletes every settlement period EXCEPT the authoritative frozen ones
(``invoiced`` = billed and immutable; ``overridden`` = a finance decision). The
deleted rows are derived (recomputed by ``QuarterlySettlementService.close`` from
aggregates + NPQP) and are regenerated, under the correct phase-anchored quarter
set, by the settlement refresh — ``GET .../settlement?refresh=true`` now
enumerates the valid quarters across ``[anchor, phase_end]`` and prunes any
survivors that fall outside it. Run that per project post-deploy.

Downgrade is an intentional no-op — the deleted rows are derived and rebuild on
the next refresh; there is nothing correct to restore. Mirrors 0031/0035–0038.

Revision ID: 0039_purge_stale_settlements
Revises:     0038_purge_aggs_reanchor
Create Date: 2026-08-17
"""
from __future__ import annotations

from alembic import op


revision = "0039_purge_stale_settlements"
down_revision = "0038_purge_aggs_reanchor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the authoritative frozen rows; purge the derived ones so they
    # regenerate under the phase anchor on the next settlement refresh.
    op.execute(
        """
        DELETE FROM contract.sla_settlement_period
         WHERE status NOT IN ('invoiced', 'overridden')
        """
    )


def downgrade() -> None:
    # Intentional no-op — settlement rows are derived and rebuild on refresh.
    pass
