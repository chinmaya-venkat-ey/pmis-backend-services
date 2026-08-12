"""SLA 007 — insert the missing resource_logged_hours bands on compound defs.

Follow-up to 0029. PMU-SLA007 is a COMBINED (business-days AND hours) SLA, and
the point_accumulation evaluator now scores every banded metric and takes the
worst severity. But the canonical live def carries the resource_logged_hours
METRIC without any resource_logged_hours BANDS — so the hours dimension is never
scored (e.g. BD 16 / hrs 100 comes back Sev 0 instead of Sev 4). The seed already
has these bands; onboarded/older rows don't. Insert them (RFP §5.28.3.e, same
values as the seed, min-EXCLUSIVE / max-INCLUSIVE):

    L0 >=144 hrs   range_min 143, range_max NULL   Sev 0
    L2 108-135 hrs range_min 107, range_max 135     Sev 2
    L4 <108 hrs    range_min NULL, range_max 107    Sev 4

Scoped to COMBINED PMU-SLA007 defs that already have the hours metric + BD bands
but NO hours bands (so it is idempotent and never duplicates). INDEPENDENT
single-metric variants are untouched.

Revision ID: 0030_sla007_hours
Revises:     0029_sla007_fix
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0030_sla007_hours"
down_revision = "0029_sla007_fix"
branch_labels = None
depends_on = None


_RE = r"^PMU[-_]SLA007([-_].*|_?)?$"

# (band_label, range_min, range_max, severity_level, sort_order)
_HOURS_BANDS = [
    ("L0 >=144 hrs", 143, None, 0, 4),
    ("L2 108-135 hrs", 107, 135, 2, 5),
    ("L4 <108 hrs", None, 107, 4, 6),
]

_INSERT = sa.text(
    """
    INSERT INTO contract.sla_condition_bands
           (id, sla_id, metric_key, band_label, range_min, range_max,
            range_unit, severity_level, sort_order, created_at)
    SELECT gen_random_uuid(), d.id, 'resource_logged_hours', :label,
           :rmin, :rmax, 'hours', :sev, :sort, now()
      FROM contract.sla_definitions d
     WHERE d.sla_ref ~ :regex
       AND d.compound_metric_rule = 'COMBINED'
       AND EXISTS (SELECT 1 FROM contract.sla_metrics m
                    WHERE m.sla_id = d.id AND m.metric_key = 'resource_logged_hours')
       AND EXISTS (SELECT 1 FROM contract.sla_condition_bands b
                    WHERE b.sla_id = d.id AND b.metric_key = 'resource_business_days')
       AND NOT EXISTS (SELECT 1 FROM contract.sla_condition_bands b
                        WHERE b.sla_id = d.id
                          AND b.metric_key = 'resource_logged_hours'
                          AND b.severity_level = :sev)
    """
)


def upgrade() -> None:
    conn = op.get_bind()
    for label, rmin, rmax, sev, sort in _HOURS_BANDS:
        conn.execute(_INSERT, {
            "label": label, "rmin": rmin, "rmax": rmax,
            "sev": sev, "sort": sort, "regex": _RE,
        })


def downgrade() -> None:
    conn = op.get_bind()
    # Remove the hours bands from COMBINED PMU-SLA007 defs (on the live target the
    # canonical carried only BD bands before this migration, so this is its exact
    # reverse). Caveat: on a fresh seeded DB where the seed already supplied hours
    # bands, upgrade was a no-op but this downgrade would remove the seed's bands —
    # re-run the seed / re-upgrade to restore them.
    conn.execute(
        sa.text(
            """
            DELETE FROM contract.sla_condition_bands b
             USING contract.sla_definitions d
             WHERE d.id = b.sla_id
               AND d.sla_ref ~ :regex
               AND d.compound_metric_rule = 'COMBINED'
               AND b.metric_key = 'resource_logged_hours'
            """
        ),
        {"regex": _RE},
    )
