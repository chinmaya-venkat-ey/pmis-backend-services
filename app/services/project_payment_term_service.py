"""ProjectPaymentTermService — the "Project Term" table.

Payment-term ROWS are auto-managed by ProjectCostItemService (one row per
milestone bound to a fixed cost row, phase taken from the cost binding). So
this service is READ + UPDATE only — the user fills in the schedule
(``frequency_code`` + ``percent_of_payment``) on each row. There is no manual
create / delete / restore.

Enforces:
  - publish-lock (admin bypass)
  - frequency_code resolves to an active master (cross-schema mirror)
  - HARD cap: the sum of percentOfPayment within a phase may not exceed 100.
    (QRG distribution GROWS a later phase's total, not its cap — so the cap
    stays a flat 100% and the bigger value comes from the larger base.)
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
from app.repositories.project_repository import ProjectRepository
from app.schemas.payment import PaymentTermUpdateRequest
from app.utilities.payment_lock import assert_payment_writable
from app.utilities.payment_masters import validate_frequency_code
from app.utilities.phase_order import order_phases

_HUNDRED = Decimal("100")


class ProjectPaymentTermService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectPaymentTermRepository(db)
        self.cost_items = ProjectCostItemRepository(db)
        self.projects = ProjectRepository(db)
        self.audit = ProjectAuditLogRepository(db)

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
        # this row) + new value must be <= 100. (A QRG share grows this phase's
        # base total, not its cap — so the cap is a flat 100% of that bigger
        # total.)
        if (
            "percent_of_payment" in updates
            and updates["percent_of_payment"] is not None
            and row.phase is not None
        ):
            new_pct = Decimal(str(updates["percent_of_payment"]))
            others = self.repo.sum_percent_for_phase(
                row.project_id, row.phase, exclude_id=row.id,
            )
            if others + new_pct > _HUNDRED:
                raise ValidationError(
                    "Total % of payment for this phase cannot exceed 100. "
                    f"Already allocated {others}%, attempted to add {new_pct}% "
                    f"(headroom {_HUNDRED - others}%).",
                )

        # The FINAL phase must be fully utilised (100%) — it has nowhere to carry
        # a shortfall forward, so any under-allocation there is lost. The
        # last-phase auto-fill only covers NULL milestones; if this update leaves
        # every milestone in the last phase EXPLICIT and the total != 100, reject
        # (mirrors the FE's "Last phase must total 100%" guard).
        if (
            "percent_of_payment" in updates
            and row.phase is not None
            and self._is_last_phase(row.project_id, row.phase)
        ):
            phase_terms = [
                t for t in self.repo.list_all_live(row.project_id) if t.phase == row.phase
            ]
            total = Decimal("0")
            all_explicit = True
            for t in phase_terms:
                val = updates["percent_of_payment"] if t.id == row.id else t.percent_of_payment
                if val is None:
                    all_explicit = False  # a null term will auto-fill the remainder
                else:
                    total += Decimal(str(val))
            if all_explicit and total != _HUNDRED:
                short = _HUNDRED - total
                raise ValidationError(
                    f"The final phase must total 100% (this would make it {total}%). "
                    + (f"Add {short}% more" if short > 0 else f"Remove {-short}%")
                    + " across its milestones, or leave one milestone blank to auto-fill.",
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

    def _is_last_phase(self, project_id: str, phase) -> bool:
        """True if ``phase`` is the chronologically LAST phase among the phases
        that carry payment terms (same date ordering the payment page uses)."""
        dates = self.cost_items.phase_milestone_date_bounds(project_id)
        phases = {t.phase for t in self.repo.list_all_live(project_id) if t.phase is not None}
        phases.add(phase)
        ordered = order_phases(phases, dates)
        return bool(ordered) and ordered[-1] == phase

    def _require_project(self, project_id: str):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        return project


def _s(value) -> Optional[str]:
    return None if value is None else str(value)
