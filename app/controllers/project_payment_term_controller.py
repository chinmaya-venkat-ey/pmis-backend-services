"""ProjectPaymentTermController — shapes Project-Term responses. The derived
``value`` needs the row's phase fixed total, so the controller loads the
project's live cost rows and applies payment_calc."""
from __future__ import annotations

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
        phase_fixed = payment_calc.phase_fixed_total(
            self.cost_items.list_all_live(row.project_id), row.phase,
        )
        return _payment_term_response(row, phase_fixed)

    def get(self, term_id: str) -> PaymentTermResponse:
        return self._to_response(self.service.get_by_id(term_id))

    def create(self, project_id, payload, *, caller_user_id, caller_is_admin=False) -> PaymentTermResponse:
        row = self.service.create(
            project_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self._to_response(row)

    def update(self, term_id, payload, *, caller_user_id, caller_is_admin=False) -> PaymentTermResponse:
        row = self.service.update(
            term_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self._to_response(row)

    def delete(self, term_id, *, caller_user_id, caller_is_admin=False) -> None:
        self.service.delete(term_id, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin)

    def restore(self, term_id, *, caller_user_id, caller_is_admin=False) -> PaymentTermResponse:
        row = self.service.restore(
            term_id, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self._to_response(row)

    def list_for_project(self, project_id, *, offset=1, page_size=50, include_deleted=False):
        rows, total = self.service.list_for_project(
            project_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )
        cost_rows = self.cost_items.list_all_live(project_id)
        items = [
            _payment_term_response(r, payment_calc.phase_fixed_total(cost_rows, r.phase))
            for r in rows
        ]
        return {
            "items": items,
            "total": total, "offset": offset, "page_size": page_size,
        }
