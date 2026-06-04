"""ProjectPaymentTermController — shapes Project-Term responses. Calculations
are ROW-based: a term's ``value`` = ``percent × its cost row's total``, so the
controller resolves each term's cost row total as the base.

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

    def _row_total_by_ci(self, project_id):
        return {
            c.id: payment_calc.row_total(c.cost, c.tax_percent)
            for c in self.cost_items.list_all_live(project_id)
        }

    def _to_response(self, row) -> PaymentTermResponse:
        base = self._row_total_by_ci(row.project_id).get(row.cost_item_id, Decimal("0"))
        return _payment_term_response(row, base)

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
        base_by_ci = self._row_total_by_ci(project_id)
        items = [
            _payment_term_response(r, base_by_ci.get(r.cost_item_id, Decimal("0")))
            for r in rows
        ]
        return {
            "items": items,
            "total": total, "offset": offset, "page_size": page_size,
        }
