"""ProjectPaymentTermService — the "Project Term" table.

Payment-term ROWS are auto-managed by ProjectCostItemService (one row per
milestone bound to a fixed cost row, phase taken from the cost binding). So
this service is READ + UPDATE only — the user fills in the schedule
(``frequency_code`` + ``percent_of_payment``) on each row. There is no manual
create / delete / restore.

Enforces:
  - publish-lock (admin bypass)
  - frequency_code resolves to an active master (cross-schema mirror)
  - HARD cap: the sum of percentOfPayment within a phase may not exceed the
    phase's EFFECTIVE cap — normally 100, but raised when the phase receives a
    QRG share from an earlier QRG phase (Option A).
Derived ``value`` is computed in the controller / page builder.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.errors import ProjectNotFoundError, ValidationError
from app.models.project_payment_term import ProjectPaymentTerm
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_cost_item_repository import ProjectCostItemRepository
from app.repositories.project_payment_term_repository import ProjectPaymentTermRepository
from app.repositories.project_phase_qrg_repository import ProjectPhaseQrgRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.payment import PaymentTermUpdateRequest
from app.utilities import payment_calc
from app.utilities.payment_lock import assert_payment_writable
from app.utilities.payment_masters import validate_frequency_code

_HUNDRED = Decimal("100")


class ProjectPaymentTermService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectPaymentTermRepository(db)
        self.projects = ProjectRepository(db)
        self.audit = ProjectAuditLogRepository(db)
        self.cost_items = ProjectCostItemRepository(db)
        self.phase_qrg = ProjectPhaseQrgRepository(db)

    # ------------------------------------------------------------------ read

    def get_by_id(self, term_id: str) -> ProjectPaymentTerm:
        row = self.repo.get_by_id(term_id)
        if row is None:
            raise ValidationError("The payment term could not be found.")
        return row

    def list_for_project(self, project_id: str, *, offset=1, page_size=50, include_deleted=False):
        self._require_project(project_id)
        return self.repo.list_for_project(
            project_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    # ----------------------------------------------------------------- write

    def update(
        self, term_id: str, payload: PaymentTermUpdateRequest, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> ProjectPaymentTerm:
        row = self.get_by_id(term_id)
        project = self._require_project(row.project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return row

        if "frequency_code" in updates:
            updates["frequency_code"] = validate_frequency_code(self.db, updates["frequency_code"])

        # HARD per-PHASE cap: Σ percentOfPayment (live, this phase, excluding
        # this row) + new value must be <= the phase's EFFECTIVE cap. The cap is
        # 100 normally, but higher when this phase receives a QRG share from an
        # earlier QRG phase (Option A — the share raises the budget).
        if (
            "percent_of_payment" in updates
            and updates["percent_of_payment"] is not None
            and row.phase is not None
        ):
            new_pct = Decimal(str(updates["percent_of_payment"]))
            others = self.repo.sum_percent_for_phase(
                row.project_id, row.phase, exclude_id=row.id,
            )
            cap = self._effective_cap(row.project_id, row.phase)
            if others + new_pct > cap:
                raise ValidationError(
                    f"Total % of payment for this phase cannot exceed {cap}. "
                    f"Already allocated {others}%, attempted to add {new_pct}% "
                    f"(headroom {cap - others}%).",
                )

        before = {k: getattr(row, k) for k in updates}
        self.repo.update(row, updated_by=caller_user_id, **updates)
        self.audit.write(
            project_id=row.project_id, target_kind="payment_term", target_id=row.id,
            action="update", actor_user_id=caller_user_id,
            changes={k: {"before": _s(before[k]), "after": _s(updates[k])} for k in updates},
        )
        self.db.commit()
        return row

    # --------------------------------------------------------------- helpers

    def _require_project(self, project_id: str):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        return project

    def _effective_cap(self, project_id: str, phase: int) -> Decimal:
        """The phase's % cap — 100 normally, raised when it receives a QRG
        share (Option A)."""
        cost_rows = self.cost_items.list_all_live(project_id)
        term_rows = self.repo.list_all_live(project_id)
        qrg_phase = self.phase_qrg.get_applied_phase(project_id)
        caps = payment_calc.qrg_caps(cost_rows, term_rows, qrg_phase)["caps"]
        return caps.get(phase, _HUNDRED)


def _s(value) -> Optional[str]:
    return None if value is None else str(value)
