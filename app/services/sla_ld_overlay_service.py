"""SLA-LD overlay for the project cost page.

Brings the SLA breach → liquidated-damages deduction onto the payment page,
per milestone: the cost page owns the milestone's scheduled payment, and
contract-management owns the SLA verdict + LD%. This joins them:

    ldAmount   = ldPercent% × milestone scheduled
    netPayable = scheduled − ldAmount

Additive and read-only — it does not touch the payment computation itself;
the FE overlays these figures on the existing cost page. (Per decision E the
contractual ``ld_computation_base`` is honoured where contract-mgmt can
resolve it; quarterly/annual bases fall back to the milestone's scheduled
payment, which is the natural per-milestone base here.)
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.milestone import Milestone
from app.services.payment_page_service import PaymentPageService
from app.services.sla_client import SlaClient


def _f(v) -> float:
    return float(v) if v is not None else 0.0


class SlaLdOverlayService:
    def __init__(self, db: Session):
        self.db = db
        self.payment = PaymentPageService(db)
        self.sla = SlaClient()

    def build(self, project_id: str) -> Dict[str, Any]:
        page = self.payment.build_page(project_id)

        scheduled_by_ms: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for ph in page.phases:
            for t in ph.payment_terms:
                if t.milestone_id:
                    scheduled_by_ms[t.milestone_id] += (t.value or Decimal("0"))

        names = dict(self.db.execute(
            select(Milestone.id, Milestone.name)
            .where(Milestone.project_id == project_id, Milestone.deleted_at.is_(None))
        ).all())

        sla_by_ms = self.sla.by_milestones(project_id)

        rows: List[Dict[str, Any]] = []
        tot_sched = tot_ld = Decimal("0")
        for ms_id, scheduled in scheduled_by_ms.items():
            s = sla_by_ms.get(ms_id, {})
            ld_pct = Decimal(str(s.get("ldPercent") or 0))
            ld_amount = (ld_pct / Decimal("100")) * scheduled
            rows.append({
                "milestoneId": ms_id,
                "milestone": names.get(ms_id),
                "scheduled": _f(scheduled),
                "slaAvailable": bool(s.get("available")),
                "compliance": s.get("compliance", 0),
                "met": s.get("met", 0), "breached": s.get("breached", 0),
                "ldPercent": _f(ld_pct),
                "ldAmount": _f(ld_amount),
                "netPayable": _f(scheduled - ld_amount),
            })
            tot_sched += scheduled
            tot_ld += ld_amount

        rows.sort(key=lambda r: (r["milestone"] or ""))
        return {
            "available": bool(sla_by_ms),
            "projectId": project_id,
            "milestones": rows,
            "totals": {
                "scheduled": _f(tot_sched),
                "ldDeduction": _f(tot_ld),
                "netPayable": _f(tot_sched - tot_ld),
            },
        }
