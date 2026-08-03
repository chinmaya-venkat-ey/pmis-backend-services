"""ProjectPaymentTermController — shapes Project-Term responses. A term's
``value`` is PHASE-based and computed on the phase's EFFECTIVE total
(``fixed [+ one-time on first] + carry-forward received``); ``rowTotal`` is the
term's own cost-row total, for information only. Partial-payment milestones'
terms also carry the per-activity split.

Payment-term rows are auto-managed (created/removed by ProjectCostItemService
from the cost milestone bundles), so this controller exposes GET + list +
PATCH only — no manual create / delete / restore."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.payment import PaymentTermResponse
from app.services.payment_page_service import PaymentPageService
from app.services.project_payment_term_service import ProjectPaymentTermService


class ProjectPaymentTermController:
    def __init__(self, db: Session):
        self.db = db
        self.service = ProjectPaymentTermService(db)
        self.page = PaymentPageService(db)

    def get(self, term_id: str) -> PaymentTermResponse:
        # Resolve via the service first so a missing term raises NotFound.
        row = self.service.get_by_id(term_id)
        return self.page.term_response(row.id)

    def update(self, term_id, payload, *, caller_user_id, caller_is_admin=False) -> PaymentTermResponse:
        row = self.service.update(
            term_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self.page.term_response(row.id)

    def list_for_project(
        self, project_id, *, offset=1, page_size=50, include_deleted=False,
        bearer_token=None,
    ):
        rows, total = self.service.list_for_project(
            project_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )
        items = self.page.list_term_responses(project_id, rows, bearer_token=bearer_token)
        return {
            "items": items,
            "total": total, "offset": offset, "page_size": page_size,
        }
