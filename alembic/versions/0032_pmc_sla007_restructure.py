"""Remediate mis-onboarded SLA007 defs: single collapsed metric -> BD+hours COMBINED.

Live projects (e.g. "Project Management Consultants (PMC)") onboarded SLA007
(minimum resource availability) via the wizard, which collapsed the RFP's TWO
metrics (business-days AND hours, §5.28.3.e) into ONE free-text metric
"minimum_resource_availability" with nonsensical bands mixing BD/hours thresholds
(e.g. range_min=16, range_max=144). Such a def cannot score correctly.

This restructures every def carrying that mis-onboarding signature into the correct
compound shape (matching the fixed canonical PMU-SLA007 + the seed):
  * rename the collapsed metric  -> resource_business_days (primary, days)
  * add                          -> resource_logged_hours (hours)
  * replace the mixed bands with proper BD bands + hours bands (min-EXCLUSIVE):
        BD:    L0 >=16 (min15) / L2 [11,15] / L4 max11
        hours: L0 >=144 (min143) / L2 [107,135] / L4 max107
  * set compound_metric_rule = COMBINED (so the evaluator scores both metrics)

Safe: existing observations on these defs carry a BLANK metric_key + scalar value
(they were single-value entries), so the metric rename does not orphan them — they
simply score on the primary (BD) on re-eval until a proper {BD,hours} value is entered.
No mapping references a metric_key. Bands are re-inserted per (metric,severity) with a
NOT-EXISTS guard so the migration is idempotent.

Revision ID: 0032_pmc_sla007
Revises:     0031_backfill_rule
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0032_pmc_sla007"
down_revision = "0031_backfill_rule"
branch_labels = None
depends_on = None

_SIGNATURE_METRIC = "minimum_resource_availability"

# (metric_key, band_label, range_min, range_max, severity, sort_order)
_BANDS = [
    ("resource_business_days", "L0 >=16 BD", 15, None, 0, 1),
    ("resource_business_days", "L2 12-15 BD", 11, 15, 2, 2),
    ("resource_business_days", "L4 <12 BD", None, 11, 4, 3),
    ("resource_logged_hours", "L0 >=144 hrs", 143, None, 0, 4),
    ("resource_logged_hours", "L2 108-135 hrs", 107, 135, 2, 5),
    ("resource_logged_hours", "L4 <108 hrs", None, 107, 4, 6),
]


def _targets(conn):
    return [r[0] for r in conn.execute(sa.text(
        "SELECT d.id FROM contract.sla_definitions d WHERE EXISTS ("
        "  SELECT 1 FROM contract.sla_metrics m WHERE m.sla_id=d.id AND m.metric_key=:mk)"
    ), {"mk": _SIGNATURE_METRIC}).fetchall()]


def upgrade() -> None:
    conn = op.get_bind()
    for sid in _targets(conn):
        # 1. collapsed metric -> business-days (primary)
        conn.execute(sa.text(
            "UPDATE contract.sla_metrics SET metric_key='resource_business_days', "
            "display_name='Business days logged (per resource per month)', unit='days', "
            "is_primary=true WHERE sla_id=:sid AND metric_key=:mk"
        ), {"sid": sid, "mk": _SIGNATURE_METRIC})
        # 2. add hours metric if absent
        conn.execute(sa.text(
            "INSERT INTO contract.sla_metrics (id, sla_id, metric_key, display_name, unit, is_primary, created_at) "
            "SELECT gen_random_uuid(), :sid, 'resource_logged_hours', "
            "'Hours logged (per resource per month)', 'hours', false, now() "
            "WHERE NOT EXISTS (SELECT 1 FROM contract.sla_metrics WHERE sla_id=:sid AND metric_key='resource_logged_hours')"
        ), {"sid": sid})
        # 3. drop the old mixed bands
        conn.execute(sa.text(
            "DELETE FROM contract.sla_condition_bands WHERE sla_id=:sid AND metric_key=:mk"
        ), {"sid": sid, "mk": _SIGNATURE_METRIC})
        # 4. insert correct BD + hours bands (idempotent per metric+severity)
        for mk, label, rmin, rmax, sev, sort in _BANDS:
            conn.execute(sa.text(
                "INSERT INTO contract.sla_condition_bands "
                "(id, sla_id, metric_key, band_label, range_min, range_max, range_unit, severity_level, sort_order, created_at) "
                "SELECT gen_random_uuid(), :sid, :mk, :label, :rmin, :rmax, :unit, :sev, :sort, now() "
                "WHERE NOT EXISTS (SELECT 1 FROM contract.sla_condition_bands "
                "  WHERE sla_id=:sid AND metric_key=:mk AND severity_level=:sev)"
            ), {"sid": sid, "mk": mk, "label": label, "rmin": rmin, "rmax": rmax,
                "unit": ("days" if mk == "resource_business_days" else "hours"),
                "sev": sev, "sort": sort})
        # 5. mark compound
        conn.execute(sa.text(
            "UPDATE contract.sla_definitions SET compound_metric_rule='COMBINED' WHERE id=:sid"
        ), {"sid": sid})


def downgrade() -> None:
    # Intentional no-op. This restructures broken defs into the RFP-correct compound
    # shape; the pre-image (a single collapsed metric with mixed-threshold bands) is
    # invalid and not worth restoring, and its exact free-text band labels can't be
    # reconstructed. Mirrors 0027/0031 (leave corrected data in place on downgrade).
    pass
