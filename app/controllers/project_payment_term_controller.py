"""ProjectPaymentTermController — shapes Project-Term responses. A term's
``value`` is PHASE-based (``percent × the whole phase total``); ``rowTotal`` is
the term's own cost-row total, surfaced for information only.

Payment-term rows are auto-managed (created/removed by ProjectCostItemService
from the cost milestone bundles), so this controller exposes GET + list +
PATCH only — no manual create / delete / restore."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.project_cost_item_repository import ProjectCostItemRepository
from app.schemas.payment import PaymentTermResponse
from app.services.payment_page_service import _payment_term_response
from app.services.project_payment_term_service import ProjectPaymentTermService
from app.utilities import payment_calc


class ProjectPaymentTermController:
    def __init__(self, db: Session):
        self.db = db
        self.service = ProjectPaymentTermService(db)
        self.cost_items = ProjectCostItemRepository(db)

    def _to_response(self, row) -> PaymentTermResponse:
        cost_rows = self.cost_items.list_all_live(row.project_id)
        phase_base = payment_calc.phase_fixed_total(cost_rows, row.phase)
        row_base = next(
            (payment_calc.row_total(c.cost, c.tax_amount) for c in cost_rows if c.id == row.cost_item_id),
            Decimal("0"),
        )
        return _payment_term_response(row, phase_base, row_base)

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
        row_total_by_ci = {c.id: payment_calc.row_total(c.cost, c.tax_amount) for c in cost_rows}
        items = [
            _payment_term_response(
                r,
                payment_calc.phase_fixed_total(cost_rows, r.phase),
                row_total_by_ci.get(r.cost_item_id, Decimal("0")),
            )
            for r in rows
        ]
        return {
            "items": items,
            "total": total, "offset": offset, "page_size": page_size,
        }
