"""Re-key existing quarterly rows from CALENDAR quarters to PROJECT-ANCHORED
quarters.

Quarters in this service are now measured FROM the project's start date (see
``app.utilities.quarter``) rather than the absolute calendar, aligning with
project-management's contract-relative period math. Two derived tables carry a
quarter identity that must move with the new convention:

    * contract.sla_quarterly_aggregate   (mapping_id, fiscal_year, quarter)
    * contract.sla_settlement_period      (project_id, fiscal_year, quarter)

For every row this migration recomputes ``(fiscal_year, quarter, quarter_start,
quarter_end)`` by mapping the row's existing ``quarter_start`` date into the
project-anchored quarter that CONTAINS it, using the project's planned
``start_date`` (read cross-schema from ``project.projects``) as the anchor.
After the re-key ``fiscal_year`` holds the 1-based CONTRACT year and ``quarter``
the 1..4 quarter within it (label ``Y{fy}-Q{q}``).

Rows whose project has no start date are left on calendar quarters (the runtime
falls back to calendar for undated projects). The stored amounts are preserved
verbatim — a calendar quarter and its containing anchored quarter cover
near-identical windows, and open quarters are refreshed by the next daily
rollup anyway; invoiced/closed rows keep their locked figures under the new
label.

Reversible: ``downgrade`` maps each row's ``quarter_start`` back to the calendar
quarter that contains it and restores calendar bounds + a calendar
``fiscal_year``. Contract-year identities (fy 1..N) and calendar-year
identities (fy 2000+) never share the same value space, so no transient
unique-constraint collision occurs mid-migration. Genuine duplicate targets
(two source rows → one destination quarter) are effectively impossible for
well-formed quarterly data; as a safety net any row whose target key is already
claimed is left untouched.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa


revision = "0028_anchor_quarters"       # 20 chars — fits VARCHAR(32)
down_revision = "0027_sla010_pmc"
branch_labels = None
depends_on = None


# (table, scope column that participates in the unique key alongside fy+quarter)
_TABLES = (
    ("sla_quarterly_aggregate", "mapping_id"),
    ("sla_settlement_period", "project_id"),
)

_IST = timezone(timedelta(hours=5, minutes=30))
_QUARTER_MONTHS = 3


# ── date math (self-contained copies — a migration must not depend on app code
#    that may change under it) ──────────────────────────────────────────────

def _ist_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(_IST)
        return value.date()
    return value  # already a date


def _add_months(d: date, n: int) -> date:
    m0 = d.year * 12 + (d.month - 1) + n
    year, month = divmod(m0, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def _anchored_key(qstart: date, anchor: date):
    """(fiscal_year, quarter, quarter_start, quarter_end) for the anchored
    quarter that contains ``qstart``."""
    months = (qstart.year - anchor.year) * 12 + (qstart.month - anchor.month)
    if qstart.day < anchor.day:
        months -= 1
    idx = months // _QUARTER_MONTHS
    if idx < 0:
        idx = 0
    start = _add_months(anchor, idx * _QUARTER_MONTHS)
    end = _add_months(anchor, (idx + 1) * _QUARTER_MONTHS) - timedelta(days=1)
    return idx // 4 + 1, idx % 4 + 1, start, end


def _calendar_key(qstart: date):
    """(fiscal_year, quarter, quarter_start, quarter_end) for the calendar
    quarter that contains ``qstart``."""
    q = (qstart.month - 1) // 3 + 1
    sm = 3 * (q - 1) + 1
    start = date(qstart.year, sm, 1)
    if q == 4:
        end = date(qstart.year, 12, 31)
    else:
        end = date(qstart.year, sm + 3, 1) - timedelta(days=1)
    return qstart.year, q, start, end


def _rekey(to_anchored: bool) -> None:
    conn = op.get_bind()
    anchors: dict = {}

    for table, scope_col in _TABLES:
        rows = conn.execute(sa.text(
            f"SELECT id, project_id, {scope_col} AS scope, quarter_start "
            f"FROM contract.{table}"
        )).mappings().all()

        claimed: set = set()
        for r in rows:
            pid = r["project_id"]
            if pid not in anchors:
                anchors[pid] = _ist_date(conn.execute(
                    sa.text("SELECT start_date FROM project.projects WHERE id = :pid"),
                    {"pid": pid},
                ).scalar())
            anchor = anchors[pid]

            qstart = r["quarter_start"]
            if to_anchored:
                if anchor is None:
                    continue  # undated project → stays on calendar quarters
                fy, q, qs, qe = _anchored_key(qstart, anchor)
            else:
                fy, q, qs, qe = _calendar_key(qstart)

            key = (r["scope"], fy, q)
            if key in claimed:
                # Two source rows collapse to one destination quarter — leave
                # this one untouched rather than violate the unique constraint.
                continue
            claimed.add(key)

            conn.execute(sa.text(
                f"UPDATE contract.{table} "
                f"SET fiscal_year = :fy, quarter = :q, "
                f"    quarter_start = :qs, quarter_end = :qe "
                f"WHERE id = :id"
            ), {"fy": fy, "q": q, "qs": qs, "qe": qe, "id": r["id"]})


def upgrade() -> None:
    _rekey(to_anchored=True)


def downgrade() -> None:
    _rekey(to_anchored=False)
