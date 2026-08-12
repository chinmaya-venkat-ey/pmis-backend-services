"""SLA 007 (Min resource availability) — correct off-by-one bands + drop the
blunt EXCLUDE guard on already-onboarded definitions.

Two live defects on existing PMU-SLA007 rows (the seed file was corrected in
733c59b, but seeds are insert-only so onboarded/older-seeded rows kept the bug):

  1. Off-by-one severity bands. The evaluator matches bands min-EXCLUSIVE /
     max-INCLUSIVE (``value > range_min AND value <= range_max``), so an
     inclusive ">= 16 BD" must be encoded as ``range_min = 15`` (SLA006 encodes
     ">= 20" as 19). The stale rows encode it as 16, so 16 BD scores Sev 2
     instead of Sev 0 and 12 BD scores Sev 4 instead of Sev 2 — a real
     over-penalisation. Same one-off on the hours bands.
         BD:    L0 16→15 ; L2 [12,16]→[11,15] ; L4 max 12→11
         hours: L0 144→143 ; L2 [108,144]→[107,135] ; L4 max 108→107

  2. Guard ``resource_logged_hours LT 144 → EXCLUDE`` fires on the WHOLE breach
     region (Sev 2 = 108-135 hrs, Sev 4 < 108), so a genuine joint breach is
     marked "excluded" and its LD suppressed. With compound (COMBINED) severity
     scoring now in the evaluator, hours are scored directly via their own bands,
     so the guard is removed.

Each band UPDATE is guarded on the exact buggy value, so ops-customised bands
are left untouched (mirrors 0027). RFP §5.28.3.e.

Revision ID: 0029_sla007_fix
Revises:     0028_anchor_quarters
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0029_sla007_fix"
down_revision = "0028_anchor_quarters"
branch_labels = None
depends_on = None


_RE = r"^PMU[-_]SLA007([-_].*|_?)?$"

# (metric_key, severity_level, correct_min, correct_max, buggy_min, buggy_max)
_BANDS = [
    ("resource_business_days", 0, 15, None, 16, None),
    ("resource_business_days", 2, 11, 15, 12, 16),
    ("resource_business_days", 4, None, 11, None, 12),
    ("resource_logged_hours", 0, 143, None, 144, None),
    ("resource_logged_hours", 2, 107, 135, 108, 144),
    ("resource_logged_hours", 4, None, 107, None, 108),
]

_BAND_UPDATE = sa.text(
    """
    UPDATE contract.sla_condition_bands b
       SET range_min = :set_min, range_max = :set_max
      FROM contract.sla_definitions d
     WHERE d.id = b.sla_id
       AND d.sla_ref ~ :regex
       AND b.metric_key = :mk
       AND COALESCE(b.severity_level, -1) = :sev
       AND b.range_min IS NOT DISTINCT FROM :where_min
       AND b.range_max IS NOT DISTINCT FROM :where_max
    """
)


def _apply_bands(conn, to_correct: bool) -> None:
    for mk, sev, cmin, cmax, bmin, bmax in _BANDS:
        # upgrade: buggy → correct ; downgrade: correct → buggy
        set_min, set_max = (cmin, cmax) if to_correct else (bmin, bmax)
        where_min, where_max = (bmin, bmax) if to_correct else (cmin, cmax)
        conn.execute(_BAND_UPDATE, {
            "regex": _RE, "mk": mk, "sev": sev,
            "set_min": set_min, "set_max": set_max,
            "where_min": where_min, "where_max": where_max,
        })


def upgrade() -> None:
    conn = op.get_bind()
    # 1. Correct the off-by-one bands (only where they hold the exact buggy value).
    _apply_bands(conn, to_correct=True)
    # 2. Drop the blunt EXCLUDE guard — compound scoring now handles hours.
    conn.execute(
        sa.text(
            """
            DELETE FROM contract.sla_guard_conditions g
             USING contract.sla_definitions d
             WHERE d.id = g.sla_id
               AND d.sla_ref ~ :regex
               AND g.metric_key = 'resource_logged_hours'
               AND g.operator = 'LT'
               AND g.action = 'EXCLUDE'
            """
        ),
        {"regex": _RE},
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Revert bands to the pre-fix (off-by-one) values.
    _apply_bands(conn, to_correct=False)
    # Re-insert the EXCLUDE guard on ACTIVE PMU-SLA007 defs that no longer have it
    # (best-effort restore of prior state).
    conn.execute(
        sa.text(
            """
            INSERT INTO contract.sla_guard_conditions
                   (id, sla_id, metric_key, operator, threshold_value, action,
                    action_description, created_at)
            SELECT gen_random_uuid(), d.id, 'resource_logged_hours', 'LT', 144,
                   'EXCLUDE',
                   'Hours below 144 — verify business-day severity with manual review.',
                   now()
              FROM contract.sla_definitions d
             WHERE d.sla_ref ~ :regex
               AND d.status = 'ACTIVE'
               AND NOT EXISTS (
                   SELECT 1 FROM contract.sla_guard_conditions g
                    WHERE g.sla_id = d.id
                      AND g.metric_key = 'resource_logged_hours'
                      AND g.operator = 'LT'
                      AND g.action = 'EXCLUDE'
               )
            """
        ),
        {"regex": _RE},
    )
