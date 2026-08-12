"""Archive structurally-unusable, never-mapped SLA definitions (reversible soft-delete).

Live-data hygiene (Round 5, Track B). The `contract` schema accumulated a batch of
broken wizard test-onboardings — ACTIVE `point_accumulation`/`band_accumulation` defs
that were **never mapped to any activity** and are **structurally unusable** (fewer than
2 condition bands, so no severity ladder, OR a both-bounds-NULL "match-everything" band
that always wins). On the remote this is ~65 defs (all timestamp/`-`/junk-ref variants).

They produce no LD (unmapped) but clutter the master catalogue and the input-variable
lookups. This migration retires them by setting `status='DELETED'` — the module's existing
soft-delete status (the delete endpoint sets exactly this; every def listing/eval filters
`status != 'DELETED'`). **Nothing is physically deleted**; the rows remain and are fully
restorable.

Scope guard rails (so only genuine junk is touched):
  * `status = 'ACTIVE'`                        — never re-touches already-retired rows
  * NOT EXISTS any mapping (active OR historic) — in-use defs are untouched
  * formula_type IN (point_accumulation, band_accumulation)
        — `fixed_escalation`/`wac` defs legitimately have 0 bands; excluded
  * (band_count < 2) OR (has a both-NULL band) — the "unusable" test
A well-formed unmapped template (>=2 proper bands) does NOT match and is left alone.

Reversible: upgrade stamps `metadata->archived_broken_0033=true` on each row it changes;
downgrade restores `status='ACTIVE'` and drops the marker for exactly those rows — the
pre-existing `DELETED` defs are never resurrected.

Revision ID: 0033_archive_broken
Revises:     0032_pmc_sla007
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0033_archive_broken"
down_revision = "0032_pmc_sla007"
branch_labels = None
depends_on = None


# ACTIVE + never mapped + point/band_accumulation + (fewer than 2 bands OR a both-null band)
_TARGET_PREDICATE = """
  d.status = 'ACTIVE'
  AND NOT EXISTS (SELECT 1 FROM contract.sla_activity_mappings m WHERE m.sla_id = d.id)
  AND EXISTS (
        SELECT 1 FROM contract.formula_library fl
        WHERE fl.id = d.formula_id
          AND fl.formula_type IN ('point_accumulation', 'band_accumulation'))
  AND (
        (SELECT count(*) FROM contract.sla_condition_bands b WHERE b.sla_id = d.id) < 2
        OR EXISTS (SELECT 1 FROM contract.sla_condition_bands b
                   WHERE b.sla_id = d.id AND b.range_min IS NULL AND b.range_max IS NULL)
      )
"""


def upgrade() -> None:
    conn = op.get_bind()
    res = conn.execute(sa.text(
        "UPDATE contract.sla_definitions d "
        "SET status = 'DELETED', updated_at = now(), "
        "    metadata = COALESCE(d.metadata, '{}'::jsonb) "
        "               || jsonb_build_object('archived_broken_0033', true) "
        f"WHERE {_TARGET_PREDICATE}"
    ))
    # rowcount is informational; alembic prints it in the log
    print(f"[0033] archived {res.rowcount} broken, unmapped SLA definitions")


def downgrade() -> None:
    conn = op.get_bind()
    res = conn.execute(sa.text(
        "UPDATE contract.sla_definitions "
        "SET status = 'ACTIVE', updated_at = now(), "
        "    metadata = metadata - 'archived_broken_0033' "
        "WHERE status = 'DELETED' "
        "  AND metadata ->> 'archived_broken_0033' = 'true'"
    ))
    print(f"[0033] restored {res.rowcount} previously-archived SLA definitions")
