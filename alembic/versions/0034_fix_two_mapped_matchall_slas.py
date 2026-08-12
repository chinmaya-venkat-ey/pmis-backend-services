"""Repair the two mapped SLA defs that carry a "match-everything" band.

Live-data hygiene (Round 5, Track B). Exactly two ACTIVE defs are BOTH mapped to a live
activity AND carry a both-bounds-NULL band (which always wins → wrong/zero severity):

  * PMC-SLA005-  (project "Project Management Consultants (PMC) — copy")
        bands split across two junk metric keys; the sev-0 band is `0..0` (min-EXCLUSIVE →
        matches nothing) and the sev-4 band is both-NULL on an orphan metric.
  * PMU-SLA009-20260715133105  (project "Project Management Consultant", a stray dup)
        a single both-NULL sev-0 band → everything scores 0 → no LD.

Neither is on a genuine production project (those — 60c67666 and d1a547ef — are clean), and
neither has any `metric_observations`, so a metric/band rebuild strands nothing.

This normalises each to its family's canonical shape (copied from the known-good defs on the
real projects, PMC-SLA005 and PMC-SLA009-):
  * SLA005: metric `number_of_resource_replacements_in_a_quarter` (count) with bands
        L0 `<=1` (NULL..1) / L4 `>1` (1..NULL)
  * SLA009: metric `delay_in_onboarding_replacement_resources` (Days) with bands
        L0 `<=21` (NULL..21) / L2 `>21` (21..NULL)

Self-selecting & idempotent: the target predicate is "ACTIVE, has an active mapping, has a
both-NULL band, family SLA005/SLA009". After the rebuild the def no longer has a both-NULL
band, so a re-run matches nothing. Only families we hold a canonical template for are
touched; anything else is skipped.

Downgrade is an intentional no-op — the pre-image (mixed junk metrics / a match-all band) is
invalid and not worth reconstructing (mirrors 0027/0031/0032).

Revision ID: 0034_fix_matchall
Revises:     0033_archive_broken
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0034_fix_matchall"
down_revision = "0033_archive_broken"
branch_labels = None
depends_on = None

# family -> (metric_key, unit, [(band_label, range_min, range_max, severity, sort_order), ...])
_CANON = {
    "SLA005": (
        "number_of_resource_replacements_in_a_quarter", "count",
        [("Up to 1 replacement", None, 1, 0, 1),
         ("Every increase of 1 replacement", 1, None, 4, 2)],
    ),
    "SLA009": (
        "delay_in_onboarding_replacement_resources", "Days",
        [("Within 21 Days from date of notification", None, 21, 0, 1),
         ("> 21 days from date of notification", 21, None, 2, 2)],
    ),
}


def _targets(conn):
    return conn.execute(sa.text(
        "SELECT d.id, d.sla_ref FROM contract.sla_definitions d "
        "WHERE d.status = 'ACTIVE' "
        "  AND EXISTS (SELECT 1 FROM contract.sla_activity_mappings m "
        "              WHERE m.sla_id = d.id AND m.status = 'ACTIVE') "
        "  AND EXISTS (SELECT 1 FROM contract.sla_condition_bands b "
        "              WHERE b.sla_id = d.id AND b.range_min IS NULL AND b.range_max IS NULL)"
    )).fetchall()


def upgrade() -> None:
    conn = op.get_bind()
    for sid, sla_ref in _targets(conn):
        fam = next((k for k in _CANON if k in (sla_ref or "").upper()), None)
        if fam is None:
            print(f"[0034] skip {sla_ref}: no canonical template for its family")
            continue
        metric_key, unit, bands = _CANON[fam]
        # rebuild metric set -> the single canonical primary metric
        conn.execute(sa.text("DELETE FROM contract.sla_condition_bands WHERE sla_id=:sid"), {"sid": sid})
        conn.execute(sa.text("DELETE FROM contract.sla_metrics WHERE sla_id=:sid"), {"sid": sid})
        conn.execute(sa.text(
            "INSERT INTO contract.sla_metrics (id, sla_id, metric_key, display_name, unit, is_primary, created_at) "
            "VALUES (gen_random_uuid(), :sid, :mk, :mk, :unit, true, now())"
        ), {"sid": sid, "mk": metric_key, "unit": unit})
        for label, rmin, rmax, sev, sort in bands:
            conn.execute(sa.text(
                "INSERT INTO contract.sla_condition_bands "
                "(id, sla_id, metric_key, band_label, range_min, range_max, range_unit, severity_level, sort_order, created_at) "
                "VALUES (gen_random_uuid(), :sid, :mk, :label, :rmin, :rmax, :unit, :sev, :sort, now())"
            ), {"sid": sid, "mk": metric_key, "label": label, "rmin": rmin, "rmax": rmax,
                "unit": unit, "sev": sev, "sort": sort})
        # single-metric ladder
        conn.execute(sa.text(
            "UPDATE contract.sla_definitions SET compound_metric_rule='INDEPENDENT', updated_at=now() WHERE id=:sid"
        ), {"sid": sid})
        print(f"[0034] rebuilt {sla_ref} ({fam}) -> 1 metric + {len(bands)} bands")


def downgrade() -> None:
    # Intentional no-op. The pre-image was a match-all / mixed-junk-metric def that could
    # never score correctly; its exact prior bands are not worth (and can't faithfully be)
    # reconstructed. Mirrors 0027/0031/0032.
    pass
