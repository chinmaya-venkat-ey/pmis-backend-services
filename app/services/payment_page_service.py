"""PaymentPageService — QRG flag, CCN cap, and the aggregated payment page.

Builds the read-only, reactive Project-Finance page (everything derived is
recomputed on every read), and owns the two small writes that don't belong
to a single row:
  - set_qrg        — per-phase "QRG Applied" upsert
  - update_ccn_cap — writes projects.ccn_cap_percent (reuses the existing
                     column; v1 finance is left untouched)

Response models are assembled here (same pattern as the v1 FinanceService,
which builds FinanceSummaryResponse in the service layer).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ProjectNotFoundError
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_cost_item_repository import ProjectCostItemRepository
from app.repositories.project_payment_term_repository import ProjectPaymentTermRepository
from app.repositories.project_phase_qrg_repository import ProjectPhaseQrgRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.payment import (
    CcnBlock,
    CostItemResponse,
    PaymentPageResponse,
    PaymentTermResponse,
    PaymentTotals,
    PhaseBlock,
    QrgResponse,
)
from app.utilities import payment_calc
from app.utilities.payment_lock import assert_payment_writable, is_payment_locked


class PaymentPageService:
    def __init__(self, db: Session):
        self.db = db
        self.projects = ProjectRepository(db)
        self.cost_items = ProjectCostItemRepository(db)
        self.payment_terms = ProjectPaymentTermRepository(db)
        self.phase_qrg = ProjectPhaseQrgRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ------------------------------------------------------------------ read

    def build_page(self, project_id: str) -> PaymentPageResponse:
        project = self._require_project(project_id)

        cost_rows = self.cost_items.list_all_live(project_id)
        ms_map = self.cost_items.milestone_ids_by_cost_item([c.id for c in cost_rows])
        term_rows = self.payment_terms.list_all_live(project_id)
        qrg_rows = self.phase_qrg.list_all_live(project_id)

        # QRG (Option A): at most one phase carries it; its leftover is split by
        # amount across later phases, raising their cap. Pure calc over rows.
        qrg_phase = self.phase_qrg.get_applied_phase(project_id)
        qrg_dist = payment_calc.qrg_caps(cost_rows, term_rows, qrg_phase)

        # Each cost row's own total (informational ``rowTotal`` per term).
        # Payment value itself is PHASE-based (see below).
        row_total_by_ci = {
            c.id: payment_calc.row_total(c.cost, c.tax_amount) for c in cost_rows
        }

        totals_d = payment_calc.contract_totals(cost_rows)
        totals = PaymentTotals(
            total_contract_cost=totals_d["total_contract_cost"],
            fixed_cost=totals_d["fixed_cost"],
            one_time_cost=totals_d["one_time_cost"],
        )

        cost_items = [
            _cost_item_response(c, ms_map.get(c.id, [])) for c in cost_rows
        ]

        # Distinct phases across cost rows, payment terms, and qrg flags.
        phases = sorted({
            p for p in (
                [c.phase for c in cost_rows]
                + [t.phase for t in term_rows]
                + [q.phase for q in qrg_rows]
            ) if p is not None
        })
        phase_blocks: List[PhaseBlock] = []
        for phase in phases:
            phase_fixed = payment_calc.phase_fixed_total(cost_rows, phase)
            terms_in_phase = [t for t in term_rows if t.phase == phase]
            term_responses = [
                _payment_term_response(
                    t, phase_fixed, row_total_by_ci.get(t.cost_item_id, Decimal("0")),
                )
                for t in terms_in_phase
            ]
            sum_percent = sum((t.percent_of_payment or Decimal("0")) for t in terms_in_phase)
            applied = phase == qrg_phase
            qrg = QrgResponse(
                phase=phase,
                applied=applied,
                # leftover (the QRG phase's distributable amount) + its percent
                percent=payment_calc.qrg_percent(sum_percent) if applied else None,
                value=qrg_dist["leftover"] if applied else None,
            )
            phase_blocks.append(PhaseBlock(
                phase=phase,
                phase_fixed_total=phase_fixed,
                payment_terms=term_responses,
                qrg=qrg,
                effective_cap_percent=qrg_dist["caps"].get(phase, Decimal("100")),
                qrg_received=qrg_dist["received"].get(phase, Decimal("0")),
            ))

        cap_pct = payment_calc.to_2dp(project.ccn_cap_percent)
        ccn = CcnBlock(
            cap_percent=cap_pct,
            value=payment_calc.ccn_value(totals.total_contract_cost, cap_pct),
        )

        return PaymentPageResponse(
            project_id=project.id,
            project_code=project.project_code,
            status=project.status,
            is_locked=is_payment_locked(project.status),
            cost_items=cost_items,
            totals=totals,
            phases=phase_blocks,
            ccn=ccn,
        )

    # ----------------------------------------------------------------- write

    def set_qrg(
        self, project_id: str, phase: int, applied: bool, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        # At most ONE phase per project may carry QRG.
        if applied:
            existing = self.phase_qrg.get_applied_phase(project_id)
            if existing is not None and existing != phase:
                raise ConflictError(
                    f"QRG is already applied to phase {existing}. Remove it from "
                    f"that phase before applying it here.",
                    code="conflict",
                    details={"project_id": project_id, "qrg_phase": existing},
                )

        row = self.phase_qrg.get_for_phase(project_id, phase)
        if row is None:
            row = self.phase_qrg.create(
                project_id=project_id, phase=phase, qrg_applied=applied,
                created_by=caller_user_id, updated_by=caller_user_id,
            )
        else:
            self.phase_qrg.update(row, qrg_applied=applied, updated_by=caller_user_id)

        # target_id is VARCHAR(36): use the row's UUID (not a composite string).
        self.audit.write(
            project_id=project_id, target_kind="phase_qrg", target_id=row.id,
            action="update", actor_user_id=caller_user_id,
            changes={"phase": phase, "qrg_applied": applied},
        )
        self.db.commit()
        # QRG ripples across phases (later-phase caps), so return the full page.
        return self.build_page(project_id)

    def update_ccn_cap(
        self, project_id: str, ccn_cap_percent: Decimal, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        before = project.ccn_cap_percent
        self.projects.update(project, updated_by=caller_user_id, ccn_cap_percent=ccn_cap_percent)
        self.audit.write(
            project_id=project_id, target_kind="project", target_id=project_id,
            action="update_ccn_cap", actor_user_id=caller_user_id,
            changes={"ccn_cap_percent": {"before": _s(before), "after": _s(ccn_cap_percent)}},
        )
        self.db.commit()
        return self.build_page(project_id)

    # --------------------------------------------------------------- helpers

    def _require_project(self, project_id: str):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        return project


def _cost_item_response(row, milestone_ids: List[str]) -> CostItemResponse:
    resp = CostItemResponse.model_validate(row)
    resp.total = payment_calc.row_total(row.cost, row.tax_amount)
    resp.milestone_ids = list(milestone_ids)
    return resp


def _payment_term_response(row, phase_base: Decimal, row_base: Decimal) -> PaymentTermResponse:
    """Value is PHASE-based: ``percent × phase_base`` (the whole phase total).
    ``row_base`` is the term's own cost-row total, surfaced as ``rowTotal``
    for information only."""
    resp = PaymentTermResponse.model_validate(row)
    resp.row_total = payment_calc.to_2dp(row_base)
    resp.value = payment_calc.payment_value(row.percent_of_payment, phase_base)
    return resp


def _s(value) -> Optional[str]:
    return None if value is None else str(value)
