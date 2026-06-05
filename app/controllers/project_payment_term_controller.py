"""ProjectPaymentTermController — shapes Project-Term responses. A term's
``value`` is PHASE-based and computed on the phase's EFFECTIVE total —
``phaseFixedTotal + qrgReceived`` (the QRG share grows the later phase's
total). ``rowTotal`` is the term's own cost-row total, for information only.

Payment-term rows are auto-managed (created/removed by ProjectCostItemService
from the cost milestone bundles), so this controller exposes GET + list +
PATCH only — no manual create / delete / restore."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.project_cost_item_repository import ProjectCostItemRepository
from app.repositories.project_payment_term_repository import ProjectPaymentTermRepository
from app.repositories.project_phase_qrg_repository import ProjectPhaseQrgRepository
from app.schemas.payment import PaymentTermResponse
from app.services.payment_page_service import _payment_term_response
from app.services.project_payment_term_service import ProjectPaymentTermService
from app.utilities import payment_calc


class ProjectPaymentTermController:
    def __init__(self, db: Session):
        self.db = db
        self.service = ProjectPaymentTermService(db)
        self.cost_items = ProjectCostItemRepository(db)
        self.payment_terms = ProjectPaymentTermRepository(db)
        self.phase_qrg = ProjectPhaseQrgRepository(db)

    def _received_by_phase(self, project_id, cost_rows) -> dict:
        term_rows = self.payment_terms.list_all_live(project_id)
        qrg_phase = self.phase_qrg.get_applied_phase(project_id)
        return payment_calc.qrg_distribution(cost_rows, term_rows, qrg_phase)["received"]

    def _effective_total(self, cost_rows, received, phase) -> Decimal:
        return payment_calc.to_2dp(
            payment_calc.phase_fixed_total(cost_rows, phase) + received.get(phase, Decimal("0"))
        )

    def _to_response(self, row) -> PaymentTermResponse:
        cost_rows = self.cost_items.list_all_live(row.project_id)
        received = self._received_by_phase(row.project_id, cost_rows)
        eff_total = self._effective_total(cost_rows, received, row.phase)
        row_base = next(
            (payment_calc.row_total(c.cost, c.tax_amount) for c in cost_rows if c.id == row.cost_item_id),
            Decimal("0"),
        )
        return _payment_term_response(row, eff_total, row_base)

    def get(self, term_id: str) -> PaymentTermResponse:
        return self._to_response(self.service.get_by_id(term_id))

    def update(self, term_id, payload, *, caller_user_id, caller_is_admin=False) -> PaymentTermResponse:
        row = self.service.update(
            term_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self._to_response(row)

    def list_for_project(self, project_id, *, offset=1, page_size=50, include_deleted=False):
        rows, total = self.service.list_for_project(
            project_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )
        cost_rows = self.cost_items.list_all_live(project_id)
        received = self._received_by_phase(project_id, cost_rows)
        row_total_by_ci = {c.id: payment_calc.row_total(c.cost, c.tax_amount) for c in cost_rows}
        items = [
            _payment_term_response(
                r,
                self._effective_total(cost_rows, received, r.phase),
                row_total_by_ci.get(r.cost_item_id, Decimal("0")),
            )
            for r in rows
        ]
        return {
            "items": items,
            "total": total, "offset": offset, "page_size": page_size,
        }
