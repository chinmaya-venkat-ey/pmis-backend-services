"""Dashboard *view* service — the four aggregated "view" payloads the
new frontend dashboard consumes:

  * ``get_summary_view``        → GET /api/v3/dashboard/summary-view
  * ``get_project_full``        → GET /api/v3/dashboard/projects/{id}/full
  * ``get_organisation_view``   → GET /api/v3/dashboard/organisation-view      (mode=all)
  * ``get_organisation_single`` → GET /api/v3/dashboard/organisations/{id}/view (mode=single)

These sit ALONGSIDE the original six ``DashboardService`` endpoints
(``/dashboard/summary``, ``/projects``, …) — nothing there changes. This
class subclasses ``DashboardService`` purely to reuse its fetch/derive
helpers (bucket math, per-project counters, vendor/division lookups) so
the delay / bucket numbers stay identical across both surfaces.

Data provenance (see the feature memo):
  * REAL, from schema ``project`` + masters mirrors: project/milestone/
    activity counts & buckets, progress, delays, organisations (vendors),
    divisions, ``contractValue`` (projects.total_project_value_excl_tax),
    cost composition & planned payment-by-phase (project_cost_items),
    approval-workflow stage counts (activity_workflow_tracker),
    projectsCompleted trend (closed projects by actual_end_date month).
  * DEGRADED (``available: false``) for now: ``sla`` / ``slaHealth`` /
    ``slaByOrganization`` (contract-mgmt does not persist compliance yet),
    ``tickets``, ``meetings`` — these are filled by the ticket/meeting
    HTTP clients in a later phase; the service accepts optional injected
    provider callables so wiring them is a one-line change.
  * STUB (no source): ``released`` / paid money, ``actualCr``,
    ``releasedCr`` → 0. Historical ``delta`` strings → ``None`` and
    ``spark`` arrays → ``[]`` until the snapshot subsystem backfills them
    (the snapshot service overlays these post-hoc).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as _date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select

from app.core.errors import NotFoundError
from app.models.activity_workflow_tracker import ActivityWorkflowTracker
from app.models.project import Project
from app.models.project_cost_item import ProjectCostItem
from app.services.dashboard_service import (
    BUCKET_COMPLETED,
    BUCKET_DELAYED,
    BUCKET_ONTRACK,
    DashboardService,
    _ist_today,
)
from app.services.dashboard_snapshot_service import DashboardSnapshotService
from app.services.meeting_client import MeetingClient
from app.services.ticket_client import TicketClient
from app.utilities.workflow_state import (
    STATE_ACTIVITY_COMPLETED,
    STATE_APPROVED,
    STATE_COMPLETED,
    STATE_PENDING_CONCERNED,
    STATE_PENDING_OWNER,
    STATE_READY,
    STATE_REJECTED,
)


# ── Approval-workflow: Java state → dashboard stage ───────────────────────
# The five stages the FE renders, in display order, each with the
# ``statusByItems`` key the project/full payload also exposes.
_APPROVAL_STAGES: Tuple[Tuple[str, str], ...] = (
    ("Draft", "idle"),
    ("Pending Division", "pending_division"),
    ("Pending Owner", "pending_owner"),
    ("Approved", "division_approved"),
    ("Rejected", "rejected"),
)
_STATE_TO_STAGE_KEY: Dict[str, str] = {
    STATE_READY: "idle",
    STATE_PENDING_CONCERNED: "pending_division",
    STATE_PENDING_OWNER: "pending_owner",
    STATE_APPROVED: "division_approved",
    STATE_COMPLETED: "division_approved",
    STATE_ACTIVITY_COMPLETED: "division_approved",
    STATE_REJECTED: "rejected",
}

# Rupees → Crore (1 Cr = 10,000,000). Used for the *Cr fields the FE labels.
_CRORE = Decimal("10000000")


def _to_num(value: Optional[Decimal]) -> float:
    """Numeric for JSON — Decimal→float, None→0. Whole rupees stay ints."""
    if value is None:
        return 0
    f = float(value)
    return int(f) if f.is_integer() else f


def _to_cr(value: Optional[Decimal]) -> float:
    if value is None:
        return 0
    cr = float((Decimal(value) / _CRORE))
    return int(cr) if cr.is_integer() else round(cr, 2)


def _pct(part: float, whole: float) -> int:
    return int(round(part * 100.0 / whole)) if whole else 0


def _sla_unavailable() -> Dict[str, Any]:
    return {"available": False, "compliance": 0, "met": 0, "breached": 0}


class DashboardViewService(DashboardService):
    """The four ``*-view`` / ``/full`` payloads. Read-only.

    The tickets / meetings blocks are sourced live from the Java
    ticket + meeting services via ``TicketClient`` / ``MeetingClient``.
    Both self-configure from settings and degrade to ``available: false``
    when their service URL is unset or a call fails — so the endpoints
    still work (with those blocks degraded) when the Java services aren't
    reachable. The caller's bearer token is threaded through so those
    services can validate it.
    """

    def __init__(self, db):
        super().__init__(db)
        self._ticket_client = TicketClient()
        self._meeting_client = MeetingClient()

    # =====================================================================
    # Real aggregations sourced from schema ``project``
    # =====================================================================

    def _project_values(
        self, project_ids: List[str],
    ) -> Dict[str, Decimal]:
        """``{project_id: contractValue}`` for the given live projects.

        Contract value = the project's ``total_project_value_excl_tax`` (TPV,
        the explicitly-agreed contract figure) when it has been set (> 0),
        otherwise a fallback to the sum of the project's cost-item lines.
        Rationale: TPV is entered separately from the cost breakdown and is
        frequently left at 0 while the cost lines are populated — the
        fallback keeps the KPI meaningful instead of showing 0. A properly
        configured project (TPV set) always shows the true contractual value.
        """
        if not project_ids:
            return {}
        tpv_rows = self.db.execute(
            select(Project.id, Project.total_project_value_excl_tax)
            .where(Project.id.in_(project_ids))
        ).all()
        cost_rows = self.db.execute(
            select(
                ProjectCostItem.project_id,
                func.coalesce(func.sum(ProjectCostItem.cost), 0),
            )
            .where(ProjectCostItem.project_id.in_(project_ids))
            .where(ProjectCostItem.deleted_at.is_(None))
            .group_by(ProjectCostItem.project_id)
        ).all()
        cost_by_pid = {pid: Decimal(total or 0) for pid, total in cost_rows}
        out: Dict[str, Decimal] = {}
        for pid, tpv in tpv_rows:
            tpv = tpv or Decimal("0")
            out[pid] = tpv if tpv > 0 else cost_by_pid.get(pid, Decimal("0"))
        return out

    def _cost_composition(
        self, project_ids: List[str],
    ) -> Dict[str, float]:
        """Sum cost-item ``cost`` across the projects, split into
        ``fixed`` / ``one_time`` / ``recurring`` (recurring = any row that
        carries a ``frequency_code``). All PLANNED amounts."""
        out = {"fixed": Decimal("0"), "one_time": Decimal("0"), "recurring": Decimal("0")}
        if not project_ids:
            return {k: _to_num(v) for k, v in out.items()}
        rows = self.db.execute(
            select(
                ProjectCostItem.cost_type_code,
                ProjectCostItem.frequency_code,
                ProjectCostItem.cost,
            )
            .where(ProjectCostItem.project_id.in_(project_ids))
            .where(ProjectCostItem.deleted_at.is_(None))
        ).all()
        for cost_type, freq, cost in rows:
            amt = cost or Decimal("0")
            if freq:
                out["recurring"] += amt
            elif (cost_type or "") == "one_time":
                out["one_time"] += amt
            else:
                out["fixed"] += amt
        return {k: _to_num(v) for k, v in out.items()}

    def _payment_by_phase(
        self, project_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """Planned payment grouped by cost-item ``phase``.

        ``scheduled`` = fixed-cost rows in the phase; ``oneTime`` =
        non-fixed rows in the phase; ``carriedOut`` = 0 (no actuals /
        invoicing yet). Phases are sorted naturally by label.
        """
        if not project_ids:
            return []
        rows = self.db.execute(
            select(
                ProjectCostItem.phase,
                ProjectCostItem.cost_type_code,
                ProjectCostItem.cost,
            )
            .where(ProjectCostItem.project_id.in_(project_ids))
            .where(ProjectCostItem.deleted_at.is_(None))
            .where(ProjectCostItem.phase.isnot(None))
        ).all()
        by_phase: Dict[str, Dict[str, Decimal]] = defaultdict(
            lambda: {"scheduled": Decimal("0"), "oneTime": Decimal("0")}
        )
        for phase, cost_type, cost in rows:
            amt = cost or Decimal("0")
            bucket = "scheduled" if (cost_type or "") == "fixed" else "oneTime"
            by_phase[phase][bucket] += amt

        def _phase_sort(label: str) -> Tuple[int, str]:
            digits = "".join(ch for ch in label if ch.isdigit())
            return (int(digits) if digits else 9999, label)

        out: List[Dict[str, Any]] = []
        for phase in sorted(by_phase, key=_phase_sort):
            vals = by_phase[phase]
            label = phase if phase.lower().startswith("phase") else f"Phase {phase}"
            out.append({
                "label": label,
                "scheduled": _to_num(vals["scheduled"]),
                "oneTime": _to_num(vals["oneTime"]),
                "carriedOut": 0,
            })
        return out

    def _scheduled_total(self, project_ids: List[str]) -> Decimal:
        """Total planned cost across all cost items (proxy for 'scheduled')."""
        if not project_ids:
            return Decimal("0")
        total = self.db.execute(
            select(func.coalesce(func.sum(ProjectCostItem.cost), 0))
            .where(ProjectCostItem.project_id.in_(project_ids))
            .where(ProjectCostItem.deleted_at.is_(None))
        ).scalar_one()
        return Decimal(total or 0)

    def _approval_stage_counts(
        self, project_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Real approval-workflow stage counts from
        ``activity_workflow_tracker`` (live rows). Returns the stage list,
        the total, per-key ``statusByItems``, and the pending count
        (pending-division + pending-owner)."""
        stmt = (
            select(ActivityWorkflowTracker.current_state, func.count())
            .where(ActivityWorkflowTracker.deleted_at.is_(None))
            .group_by(ActivityWorkflowTracker.current_state)
        )
        if project_ids is not None:
            if not project_ids:
                by_key = {key: 0 for _label, key in _APPROVAL_STAGES}
                return {
                    "stages": [{"label": lbl, "value": 0} for lbl, _ in _APPROVAL_STAGES],
                    "total": 0, "statusByItems": by_key, "pending": 0,
                }
            stmt = stmt.where(ActivityWorkflowTracker.project_id.in_(project_ids))

        by_key: Dict[str, int] = {key: 0 for _label, key in _APPROVAL_STAGES}
        total = 0
        for state, cnt in self.db.execute(stmt).all():
            key = _STATE_TO_STAGE_KEY.get((state or "").upper())
            if key is None:
                continue
            by_key[key] += cnt
            total += cnt
        stages = [
            {"label": label, "value": by_key[key]}
            for label, key in _APPROVAL_STAGES
        ]
        pending = by_key["pending_division"] + by_key["pending_owner"]
        return {"stages": stages, "total": total, "statusByItems": by_key, "pending": pending}

    def _monthly_trend(self, project_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Last 6 calendar months (oldest→newest). ``projectsCompleted`` =
        closed projects whose ``actual_end_date`` falls in that month.
        ``releasedCr`` = 0 (no released-money series exists yet)."""
        today = _ist_today()
        # Build the 6-month window ending on the current month.
        months: List[Tuple[int, int]] = []
        y, m = today.year, today.month
        for _ in range(6):
            months.append((y, m))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        months.reverse()

        stmt = (
            select(Project.actual_end_date)
            .where(Project.deleted_at.is_(None))
            .where(Project.status == "closed")
            .where(Project.actual_end_date.isnot(None))
        )
        if project_ids is not None:
            if not project_ids:
                closed_dates: List[Any] = []
            else:
                stmt = stmt.where(Project.id.in_(project_ids))
                closed_dates = [r[0] for r in self.db.execute(stmt).all()]
        else:
            closed_dates = [r[0] for r in self.db.execute(stmt).all()]

        counts: Dict[Tuple[int, int], int] = defaultdict(int)
        for dt in closed_dates:
            if dt is None:
                continue
            counts[(dt.year, dt.month)] += 1

        _MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return [
            {"month": _MON[mm - 1], "projectsCompleted": counts.get((yy, mm), 0), "releasedCr": 0}
            for (yy, mm) in months
        ]

    # -- KPI helpers ------------------------------------------------------

    @staticmethod
    def _status_block(buckets: List[str]) -> Dict[str, int]:
        """``{total, completed, ontrack, delayed, active}`` — active = total−completed."""
        total = len(buckets)
        completed = sum(1 for b in buckets if b == BUCKET_COMPLETED)
        ontrack = sum(1 for b in buckets if b == BUCKET_ONTRACK)
        delayed = sum(1 for b in buckets if b == BUCKET_DELAYED)
        return {
            "total": total, "completed": completed, "ontrack": ontrack,
            "delayed": delayed, "active": total - completed,
        }

    @staticmethod
    def _max_delay_over(counters: Dict[str, Dict[str, int]], project_ids: List[str]) -> int:
        return max((counters[pid]["maxDelayDays"] for pid in project_ids), default=0)

    def _tickets_block(
        self, *, bearer: Optional[str] = None, project_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return self._ticket_client.summary(bearer=bearer, project_ids=project_ids)

    def _meetings_block(
        self, *, bearer: Optional[str] = None, project_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return self._meeting_client.summary(bearer=bearer, project_ids=project_ids)

    # =====================================================================
    # Snapshot-backed metrics (delta / spark)
    # =====================================================================

    def current_global_metrics(self) -> Dict[str, Decimal]:
        """The current global KPI values the snapshot cron persists. Same
        numbers get_summary_view surfaces, as raw Decimals."""
        today = _ist_today()
        projects, _counters, _vbp, derived = self._fetch_projects_with_buckets(today_ist=today)
        pids = [p.id for p in projects]
        status = self._status_block([derived[p.id][1] for p in projects])
        contract_total = sum(self._project_values(pids).values(), Decimal("0"))
        return {
            "total_projects": Decimal(status["total"]),
            "ontrack_pct": Decimal(_pct(status["ontrack"], status["total"])),
            "delayed_projects": Decimal(status["delayed"]),
            "contract_value": contract_total,
            "released": Decimal("0"),
            "sla_compliance": Decimal("0"),
        }

    # =====================================================================
    # Endpoint 1 — GET /api/v3/dashboard/summary-view
    # =====================================================================

    def get_summary_view(
        self, *, delay_min_days: int = 1, top_n: int = 5, bearer: Optional[str] = None,
    ) -> Dict[str, Any]:
        today = _ist_today()
        projects, counters, vendors_by_pid, derived = (
            self._fetch_projects_with_buckets(today_ist=today)
        )
        pids = [p.id for p in projects]
        buckets = [derived[p.id][1] for p in projects]
        status = self._status_block(buckets)
        values = self._project_values(pids)
        contract_total = sum(values.values(), Decimal("0"))
        with_finance = sum(1 for v in values.values() if v and v > 0)

        div_labels = self._get_division_labels()

        # per-vendor and per-division rollups (project full value attributed
        # to each linked vendor / to the owning division).
        org_agg: Dict[str, Dict[str, Any]] = {}
        div_agg: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "value": Decimal("0"), "delayed": 0}
        )
        for p in projects:
            b = derived[p.id][1]
            val = values.get(p.id, Decimal("0"))
            is_delayed = 1 if b == BUCKET_DELAYED else 0
            for vid, vname, vactive in vendors_by_pid.get(p.id, []):
                meta = org_agg.setdefault(
                    vid, {"name": vname, "total": 0, "value": Decimal("0"), "delayed": 0}
                )
                meta["total"] += 1
                meta["value"] += val
                meta["delayed"] += is_delayed
            code = (p.owner or "").lower() or "unspecified"
            d = div_agg[code]
            d["total"] += 1
            d["value"] += val
            d["delayed"] += is_delayed

        top_orgs = sorted(
            org_agg.values(), key=lambda r: (-r["total"], r["name"])
        )[:top_n]
        top_divisions = sorted(
            (
                {
                    "name": (div_labels.get(code, code) if code != "unspecified" else "Unspecified"),
                    "total": v["total"], "value": _to_num(v["value"]), "delayed": v["delayed"],
                }
                for code, v in div_agg.items()
            ),
            key=lambda r: (-r["total"], r["name"]),
        )[:top_n]

        payment_by_org = [
            {"name": o["name"], "contractValue": _to_num(o["value"])}
            for o in sorted(org_agg.values(), key=lambda r: -r["value"])[:top_n]
        ]

        approvals = self._approval_stage_counts()
        max_delay = self._max_delay_over(counters, pids)

        # delta/spark come from persisted snapshots (see DashboardSnapshotService);
        # with no history yet they degrade to (None, []).
        snap = DashboardSnapshotService(self.db)
        ontrack_pct = _pct(status["ontrack"], status["total"])

        def ds(metric: str, current) -> Tuple[Optional[str], List]:
            return snap.delta_spark(metric, Decimal(current), today=today)

        tp_delta, tp_spark = ds("total_projects", status["total"])
        ot_delta, _ = ds("ontrack_pct", ontrack_pct)
        dl_delta, dl_spark = ds("delayed_projects", status["delayed"])
        cv_delta, cv_spark = ds("contract_value", contract_total)
        rl_delta, rl_spark = ds("released", 0)
        sla_delta, _ = ds("sla_compliance", 0)

        kpis = {
            "totalProjects": {
                "value": status["total"], "active": status["active"],
                "completed": status["completed"], "delta": tp_delta, "spark": tp_spark,
            },
            "onTrackPct": {"value": ontrack_pct, "delta": ot_delta},
            "delayedProjects": {
                "value": status["delayed"], "maxDelayDays": max_delay,
                "delta": dl_delta, "spark": dl_spark,
            },
            "contractValue": {
                "value": _to_num(contract_total), "withFinance": with_finance,
                "projectCount": status["total"], "delta": cv_delta, "spark": cv_spark,
            },
            "released": {"value": 0, "pctOfContract": 0, "delta": rl_delta, "spark": rl_spark},
            "slaCompliance": {"value": 0, "met": 0, "breached": 0, "delta": sla_delta},
        }

        tickets = self._tickets_block(bearer=bearer, project_ids=pids)
        return {
            "kpis": kpis,
            "projectStatus": status,
            "paymentByPhase": self._payment_by_phase(pids),
            "costComposition": self._cost_composition(pids),
            "paymentByOrganization": payment_by_org,
            "slaHealth": _sla_unavailable(),
            "approvalWorkflow": {
                "available": True, "total": approvals["total"], "stages": approvals["stages"],
            },
            "monthlyTrend": self._monthly_trend(),
            "tickets": tickets,
            "meetings": self._meetings_block(bearer=bearer, project_ids=pids),
            "topOrganizations": [
                {"name": o["name"], "total": o["total"],
                 "value": _to_num(o["value"]), "delayed": o["delayed"]}
                for o in top_orgs
            ],
            "topDivisions": top_divisions,
            "delayedTrack": self._summary_delayed_track(
                projects=projects, counters=counters, vendors_by_pid=vendors_by_pid,
                div_labels=div_labels, delay_min_days=delay_min_days, top_n=top_n,
            ),
            "escalationsTriggered": tickets.get("escalations", []),
        }

    def _summary_delayed_track(
        self, *, projects, counters, vendors_by_pid, div_labels, delay_min_days, top_n,
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for p in projects:
            c = counters[p.id]
            if c["delayedItemCount"] <= 0 or c["maxDelayDays"] < delay_min_days:
                continue
            vendors = vendors_by_pid.get(p.id, [])
            owner = (p.owner or "")
            rows.append({
                "projectId": p.id,
                "projectCode": p.project_code,
                "name": p.name,
                "organisation": vendors[0][1] if vendors else None,
                "division": div_labels.get(owner.lower(), owner) if owner else None,
                "delayedItems": c["delayedItemCount"],
                "maxDelayDays": c["maxDelayDays"],
            })
        rows.sort(key=lambda r: (r["delayedItems"], r["maxDelayDays"]), reverse=True)
        return rows[:top_n] if top_n else rows

    # =====================================================================
    # Endpoint 2 — GET /api/v3/dashboard/projects/{id}/full
    # =====================================================================

    def get_project_full(self, *, project_id: str) -> Dict[str, Any]:
        today = _ist_today()
        projects = self._list_live_projects(ids=[project_id])
        if not projects:
            raise NotFoundError("The project could not be found.")
        project = projects[0]

        counters = self._fetch_per_project_counters(
            project_ids=[project_id], today_ist=today,
        )[project_id]
        vendors = self._fetch_vendors_for_projects(project_ids=[project_id]).get(project_id, [])
        progress_pct, bucket = self._derive_progress_and_bucket(
            counters=counters, lifecycle_status=project.status,
        )
        div_labels = self._get_division_labels()
        owner = project.owner or ""

        values = self._project_values([project_id])
        contract_value = values.get(project_id, Decimal("0"))
        scheduled = self._scheduled_total([project_id])
        composition = self._cost_composition([project_id])
        approvals = self._approval_stage_counts(project_ids=[project_id])

        m_total = counters["milestonesTotal"]
        m_done = counters["milestonesCompleted"]
        a_total = counters["activitiesTotal"]
        a_done = counters["activitiesCompleted"]
        item_total = m_total + a_total
        item_done = m_done + a_done
        delayed = counters["milestonesDelayed"] + counters["activitiesDelayed"]

        # header
        organisation = vendors[0] if vendors else None
        project_block = {
            "id": project.id,
            "projectCode": project.project_code,
            "name": project.name,
            "description": project.description,
            "organisation": organisation[1] if organisation else None,
            "organisationId": organisation[0] if organisation else None,
            "division": div_labels.get(owner.lower(), owner) if owner else None,
            "divisionCode": owner or None,
            "owner": None,
            "lifecycleStatus": (project.status or "").upper() or None,
            "plannedStart": _isodate(project.start_date),
            "plannedEnd": _isodate(project.end_date),
            "actualStart": _isodate(project.actual_start_date),
            "actualEnd": _isodate(project.actual_end_date),
        }

        kpis = {
            "overallProgress": {"value": progress_pct, "delta": None},
            "milestones": {"done": m_done, "total": m_total, "pct": _pct(m_done, m_total)},
            "activities": {"done": a_done, "total": a_total, "pct": _pct(a_done, a_total)},
            "delayedItems": {"value": counters["delayedItemCount"], "maxDelayDays": counters["maxDelayDays"]},
            "pendingApprovals": {"value": approvals["pending"], "delta": None},
            "budget": {
                "contractValue": _to_num(contract_value),
                "released": 0,
                "pctOfContract": _pct(float(scheduled), float(contract_value)),
            },
        }

        finance = {
            "hasData": bool(contract_value or scheduled),
            "contractValue": _to_num(contract_value),
            "scheduled": _to_num(scheduled),
            "scheduledPctOfContract": _pct(float(scheduled), float(contract_value)),
            "fixedCost": composition["fixed"],
            "oneTimeCost": composition["one_time"],
            "recurringCost": composition["recurring"],
            "byPhase": self._payment_by_phase([project_id]),
        }

        items = self._project_full_items(project_id=project_id, today=today)
        status_counts = self._status_block(
            [BUCKET_COMPLETED] * item_done
            + [BUCKET_DELAYED] * delayed
            + [BUCKET_ONTRACK] * (item_total - item_done - delayed)
        )

        return {
            "project": project_block,
            "kpis": kpis,
            "statusCounts": status_counts,
            "finance": finance,
            "paymentTimeline": self._payment_timeline(project_id),
            "sla": {"available": False, "compliance": 0, "met": 0, "breached": 0, "breaches": []},
            "approvals": {
                "available": True,
                "pending": approvals["pending"],
                "workflow": approvals["stages"],
                "statusByItems": approvals["statusByItems"],
            },
            "delayedTrack": [
                {"wbs": r["wbs"], "name": r["name"], "kind": r["kind"],
                 "delay": r["daysDelayed"], "plannedEnd": r["plannedEnd"], "actualEnd": r["actualEnd"]}
                for r in items if r["bucket"] == BUCKET_DELAYED
            ],
            "items": items,
        }

    def _payment_timeline(self, project_id: str) -> List[Dict[str, Any]]:
        """Planned-only monthly payment timeline. No actuals series exists,
        so ``actualCr`` = 0. Currently returns an empty series (planned
        payment-by-month derivation is part of the finance follow-up)."""
        return []

    def _activity_approval_states(self, project_id: str) -> Dict[str, str]:
        """``{activity_id: fe_state_code}`` from the live workflow tracker
        (idle / pending_division / pending_owner / division_approved /
        rejected). Missing activities → no entry (approvalState=None)."""
        rows = self.db.execute(
            select(ActivityWorkflowTracker.activity_id, ActivityWorkflowTracker.current_state)
            .where(ActivityWorkflowTracker.project_id == project_id)
            .where(ActivityWorkflowTracker.deleted_at.is_(None))
        ).all()
        out: Dict[str, str] = {}
        for aid, state in rows:
            key = _STATE_TO_STAGE_KEY.get((state or "").upper())
            if key is not None:
                out[aid] = key
        return out

    def _project_full_items(self, *, project_id: str, today: _date) -> List[Dict[str, Any]]:
        """Flat milestone+activity item rows with bucket, progress, delay."""
        from app.services.dashboard_service import _item_bucket, _item_delay_days, _progress_pct

        approval_states = self._activity_approval_states(project_id)
        milestone_rows = self._fetch_milestone_rows(project_id=project_id)
        m_index_by_id: Dict[str, int] = {}
        m_name_by_id: Dict[str, str] = {}
        for idx, m in enumerate(milestone_rows, start=1):
            m_index_by_id[m[0]] = idx
            m_name_by_id[m[0]] = m[1]

        activity_rows = self._fetch_activity_rows(project_id=project_id)
        activities_by_m: Dict[str, List[Any]] = defaultdict(list)
        for a in activity_rows:
            activities_by_m[a[1]].append(a)

        out: List[Dict[str, Any]] = []
        for idx, m in enumerate(milestone_rows, start=1):
            (mid, mname, _pos, mstatus, mstart, mend, mas, mae) = m
            children = activities_by_m.get(mid, [])
            child_done = sum(1 for c in children if (c[4] or "") == "completed")
            out.append({
                "kind": "milestone", "id": mid,
                "milestoneId": None, "milestoneName": None,
                "wbs": f"{idx}", "name": mname,
                "bucket": _item_bucket(mstatus, mend, today),
                "progressPct": _progress_pct(child_done, len(children)),
                "plannedStart": _isodate(mstart), "plannedEnd": _isodate(mend),
                "actualStart": _isodate(mas), "actualEnd": _isodate(mae),
                "daysDelayed": _item_delay_days(mstatus, mend, today),
            })
            ai = 0
            for a in children:
                ai += 1
                (aid, amid, aname, _apos, astatus, astart, aend, aas, aae) = a
                out.append({
                    "kind": "activity", "id": aid,
                    "milestoneId": amid, "milestoneName": m_name_by_id.get(amid),
                    "wbs": f"{idx}.{ai}", "name": aname,
                    "bucket": _item_bucket(astatus, aend, today),
                    "progressPct": 100 if (astatus or "") == "completed" else 0,
                    "plannedStart": _isodate(astart), "plannedEnd": _isodate(aend),
                    "actualStart": _isodate(aas), "actualEnd": _isodate(aae),
                    "daysDelayed": _item_delay_days(astatus, aend, today),
                    "approvalState": approval_states.get(aid),
                })
        return out

    # =====================================================================
    # Endpoint 3 — GET /api/v3/dashboard/organisation-view  (mode=all)
    # =====================================================================

    def get_organisation_view(self, *, top_n: int = 8) -> Dict[str, Any]:
        today = _ist_today()
        vendors = self._list_live_vendors()
        projects, counters, vendors_by_pid, derived = (
            self._fetch_projects_with_buckets(today_ist=today)
        )
        pids = [p.id for p in projects]
        buckets = [derived[p.id][1] for p in projects]
        status = self._status_block(buckets)
        values = self._project_values(pids)
        contract_total = sum(values.values(), Decimal("0"))
        with_finance = sum(1 for v in values.values() if v and v > 0)

        # per-vendor rollup
        org_rows: Dict[str, Dict[str, Any]] = {}
        for p in projects:
            b = derived[p.id][1]
            val = values.get(p.id, Decimal("0"))
            for vid, vname, _vactive in vendors_by_pid.get(p.id, []):
                meta = org_rows.setdefault(vid, {
                    "organisationId": vid, "name": vname, "total": 0,
                    "completed": 0, "ontrack": 0, "delayed": 0,
                    "contractValue": Decimal("0"), "scheduled": Decimal("0"),
                })
                meta["total"] += 1
                if b == BUCKET_COMPLETED:
                    meta["completed"] += 1
                elif b == BUCKET_DELAYED:
                    meta["delayed"] += 1
                else:
                    meta["ontrack"] += 1
                meta["contractValue"] += val
        # scheduled per org (one query per org kept simple; org count is small)
        for vid, meta in org_rows.items():
            org_pids = self._fetch_project_ids_for_vendor(vid)
            meta["scheduled"] = self._scheduled_total(org_pids)

        organizations = [
            {
                "organisationId": m["organisationId"], "name": m["name"],
                "total": m["total"], "completed": m["completed"],
                "ontrack": m["ontrack"], "delayed": m["delayed"],
                "contractValue": _to_num(m["contractValue"]),
                "scheduled": _to_num(m["scheduled"]),
            }
            for m in sorted(org_rows.values(), key=lambda r: (-r["total"], r["name"]))
        ]
        leaderboard = [
            {"name": m["name"], "projects": m["total"]}
            for m in sorted(org_rows.values(), key=lambda r: (-r["total"], r["name"]))[:top_n]
        ]
        payment_by_org = [
            {"name": m["name"], "contractValue": _to_num(m["contractValue"])}
            for m in sorted(org_rows.values(), key=lambda r: -r["contractValue"])[:top_n]
        ]

        return {
            "mode": "all",
            "kpis": {
                "totalOrganizations": {
                    "value": len(vendors),
                    "active": sum(1 for v in vendors if v.active),
                    "inactive": sum(1 for v in vendors if not v.active),
                },
                "totalProjects": {
                    "value": status["total"], "active": status["active"],
                    "completed": status["completed"],
                },
                "contractValue": {
                    "value": _to_num(contract_total), "withFinance": with_finance,
                    "projectCount": status["total"],
                },
                "released": {"value": 0, "pctOfContract": 0},
                "delayedProjects": {"value": status["delayed"]},
                "slaCompliance": {"value": 0},
            },
            "projectStatus": status,
            "leaderboard": leaderboard,
            "paymentByOrganization": payment_by_org,
            "slaByOrganization": [],
            "organizations": organizations,
        }

    # =====================================================================
    # Endpoint 4 — GET /api/v3/dashboard/organisations/{id}/view (mode=single)
    # =====================================================================

    def get_organisation_single(
        self, *, organisation_id: str, bearer: Optional[str] = None,
    ) -> Dict[str, Any]:
        today = _ist_today()
        vendor = self._get_vendor(organisation_id)
        if vendor is None:
            raise NotFoundError("The organisation could not be found.")

        all_vendors = self._list_live_vendors()
        project_ids = self._fetch_project_ids_for_vendor(organisation_id)
        projects, counters, vendors_by_pid, derived = (
            self._fetch_projects_with_buckets(today_ist=today, project_ids=project_ids)
        )
        pids = [p.id for p in projects]
        buckets = [derived[p.id][1] for p in projects]
        status = self._status_block(buckets)
        values = self._project_values(pids)
        total_value = sum(values.values(), Decimal("0"))
        scheduled = self._scheduled_total(pids)
        approvals = self._approval_stage_counts(project_ids=pids)  # noqa: F841 (future use)

        payment_by_project = [
            {"projectCode": p.project_code, "contractValue": _to_num(values.get(p.id, Decimal("0")))}
            for p in sorted(projects, key=lambda p: -float(values.get(p.id, Decimal("0"))))
        ]

        top_delayed = sorted(
            (
                {
                    "projectCode": p.project_code, "name": p.name,
                    "delayedItems": counters[p.id]["delayedItemCount"],
                    "maxDelayDays": counters[p.id]["maxDelayDays"],
                }
                for p in projects if counters[p.id]["delayedItemCount"] > 0
            ),
            key=lambda r: (r["delayedItems"], r["maxDelayDays"]), reverse=True,
        )

        project_cards = [
            {
                "projectCode": p.project_code, "id": p.id, "name": p.name,
                "status": derived[p.id][1], "progressPct": derived[p.id][0],
                "contractValue": _to_num(values.get(p.id, Decimal("0"))),
                "scheduled": _to_num(self._scheduled_total([p.id])),
                "delayed": counters[p.id]["delayedItemCount"],
                "maxDelayDays": counters[p.id]["maxDelayDays"],
                "plannedEnd": _isodate(p.end_date),
            }
            for p in projects
        ]

        tickets = self._tickets_block(bearer=bearer, project_ids=pids)
        meetings = self._meetings_block(bearer=bearer, project_ids=pids)

        return {
            "mode": "single",
            "organisationId": vendor.id,
            "name": vendor.name,
            "organisations": [
                {"organisationId": v.id, "name": v.name} for v in all_vendors
            ],
            "kpis": {
                "totalProjects": {
                    "value": status["total"], "active": status["active"],
                    "completed": status["completed"],
                },
                "totalValue": {"value": _to_num(total_value)},
                "scheduledPayout": {
                    "value": _to_num(scheduled),
                    "pctOfValue": _pct(float(scheduled), float(total_value)),
                },
                "delayedProjects": {"value": status["delayed"]},
                "slaCompliance": {"value": 0},
                "openTickets": {
                    "value": tickets.get("open", 0),
                    "highPriority": tickets.get("highPriority", 0),
                    "meetings": meetings.get("upcoming", 0),
                },
            },
            "projectStatus": status,
            "projectsOverview": {
                "inProgress": status["ontrack"], "completed": status["completed"],
                "delayed": status["delayed"], "notStarted": 0,
            },
            "paymentByProject": payment_by_project,
            "contractVsScheduled": {
                "scheduled": _to_num(scheduled),
                "remaining": _to_num(total_value - scheduled),
            },
            "topDelayedProjects": top_delayed,
            "sla": {"available": False, "compliance": 0, "met": 0, "breached": 0},
            "tickets": tickets,
            "meetings": meetings,
            "projects": project_cards,
        }


def _isodate(dt) -> Optional[str]:
    """Date-only ISO string (YYYY-MM-DD) for the spec's date fields."""
    if dt is None:
        return None
    try:
        return dt.date().isoformat()
    except AttributeError:
        return dt.isoformat()
