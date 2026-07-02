"""ProjectCostItemService — business logic for the "Project Cost" table.

Owns create / update / delete / restore of cost rows plus the milestone
bundle binding. Enforces:
  - publish-lock (admin bypass) via app.utilities.payment_lock
  - cost_type_code is REQUIRED and resolves to an active master
  - ``fixed`` rows require a phase (>= 0); ``one_time`` rows carry no phase /
    no milestones, and only one live one-time row per project
  - bound milestones belong to the project (live) and a milestone belongs to
    exactly ONE live cost row (hence one phase)

Auto-sync (the cost ↔ payment-term link): after EVERY cost write the
payment-term rows are reconciled to exactly match the milestones bound to
the live FIXED cost rows — one payment-term row per milestone per phase.
Adding a milestone to a cost row materialises its payment-term row (restoring
a previously-removed one to preserve the entered frequency/percent); removing
it soft-deletes the row. The user only fills frequency + percent on those rows.

Transactions commit once at the end. Derived ``total`` is computed in the
controller (payment_calc); the service returns the ORM row.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ProjectNotFoundError, ValidationError
from app.models.milestone import Milestone
from app.models.project_cost_item import ProjectCostItem
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_cost_item_repository import ProjectCostItemRepository
from app.repositories.project_payment_term_repository import ProjectPaymentTermRepository
from app.repositories.project_phase_cf_allocation_repository import (
    ProjectPhaseCfAllocationRepository,
)
from app.repositories.project_phase_qrg_repository import ProjectPhaseQrgRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.payment import CostItemCreateRequest, CostItemUpdateRequest
from app.utilities.payment_lock import assert_payment_writable
from app.utilities.payment_masters import validate_cost_type_code
from app.utilities.phase_order import order_phases

FIXED = "fixed"
ONE_TIME = "one_time"
RESOURCE_COST = "resource_cost"
TRANSACTION_COST = "transaction_cost"
EXPENSE_TYPES = (RESOURCE_COST, TRANSACTION_COST)


class ProjectCostItemService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectCostItemRepository(db)
        self.payment_terms = ProjectPaymentTermRepository(db)
        self.phase_qrg = ProjectPhaseQrgRepository(db)
        self.cf_allocations = ProjectPhaseCfAllocationRepository(db)
        self.projects = ProjectRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ------------------------------------------------------------------ read

    def get_by_id(self, cost_item_id: str) -> ProjectCostItem:
        row = self.repo.get_by_id(cost_item_id)
        if row is None:
            raise ValidationError("The cost item could not be found.")
        return row

    def list_for_project(self, project_id: str, *, offset=1, page_size=50, include_deleted=False):
        self._require_project(project_id)
        return self.repo.list_for_project(
            project_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    def available_milestones(self, project_id: str, *, exclude_cost_item_id: Optional[str] = None):
        """Live project milestones NOT yet bound to another live cost row —
        the set the FE should offer in the cost-row milestone picker. When
        editing a cost row, pass its id as ``exclude_cost_item_id`` so the
        row's own milestones remain selectable. Returns (id, position, name)
        tuples ordered by position."""
        self._require_project(project_id)
        bound = self.repo.bound_milestone_ids(
            project_id, exclude_cost_item_id=exclude_cost_item_id,
        )
        rows = self.db.execute(
            select(Milestone.id, Milestone.position, Milestone.name)
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
            .order_by(Milestone.position.asc())
        ).all()
        return [(mid, pos, name) for mid, pos, name in rows if mid not in bound]

    # ----------------------------------------------------------------- write

    def create(
        self, project_id: str, payload: CostItemCreateRequest, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> ProjectCostItem:
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        cost_type = validate_cost_type_code(self.db, payload.cost_type_code)
        if cost_type is None:
            raise ValidationError("Cost type is required.")
        phase = payload.phase
        milestone_ids = list(payload.milestone_ids or [])
        per_txn = None
        planned = None
        label = None
        billed_mode = None
        billed_value = None

        # One-time is a single standalone amount: no phase, no milestones.
        if cost_type == ONE_TIME:
            phase = None
            milestone_ids = []
        elif cost_type == FIXED:
            if phase is None:
                raise ValidationError("Phase is required for a fixed cost row.")
            # A fixed (delivery) row must bill against at least one milestone —
            # otherwise it is a phase with value but nothing to pay it out (the
            # phantom / stranded-value case). Every phase is therefore payable.
            if not milestone_ids:
                raise ValidationError("A fixed cost row needs at least one milestone.")
        elif cost_type in EXPENSE_TYPES:
            # Resource / transaction cost: a standalone labelled expense line that
            # attaches to an EXISTING fixed phase; no deliverable-milestone binding.
            self._assert_expense_phase(project_id, phase, cost_type)
            milestone_ids = []
            label = payload.line_label
            if cost_type == TRANSACTION_COST:
                per_txn = payload.per_transaction_cost
                planned = payload.planned_transactions
            # Billed split — default fully billed (100%); the unbilled remainder
            # carries forward. The last phase can't carry, so must stay at 100%.
            billed_mode = (payload.billed_mode or "percent")
            billed_value = payload.billed_value if payload.billed_value is not None else Decimal("100")
            self._assert_expense_billed(
                project_id, phase, cost_type, billed_mode, billed_value,
                per_txn, planned, payload.cost, payload.tax_amount)

        if milestone_ids:
            self._validate_milestones(project_id, milestone_ids)
            self._assert_milestones_free(project_id, milestone_ids, exclude_id=None)

        # Position always server-assigned (append) — see TaskService.create.
        position = self.repo.next_position_for_project(project_id)

        try:
            row = self.repo.create(
                project_id=project_id,
                cost_type_code=cost_type,
                phase=phase,
                cost=payload.cost,
                tax_amount=payload.tax_amount,
                tax_percent=payload.tax_percent,
                per_transaction_cost=per_txn,
                planned_transactions=planned,
                line_label=label,
                billed_mode=billed_mode,
                billed_value=billed_value,
                position=position,
                created_by=caller_user_id,
                updated_by=caller_user_id,
            )
            self.db.flush()
        except Exception as exc:  # pragma: no cover - surfaced as friendly 409
            self.db.rollback()
            raise self._conflict_or_raise(exc, project_id)

        if milestone_ids:
            self.repo.replace_milestones(row.id, milestone_ids)

        self.audit.write(
            project_id=project_id, target_kind="cost_item", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"cost_type_code": cost_type, "phase": phase},
        )
        self._reconcile_payment_terms(project_id, caller_user_id)
        self.db.commit()
        row._milestone_ids = milestone_ids
        return row

    def update(
        self, cost_item_id: str, payload: CostItemUpdateRequest, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> ProjectCostItem:
        row = self.get_by_id(cost_item_id)
        project = self._require_project(row.project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        updates = payload.model_dump(exclude_unset=True)
        milestone_ids = updates.pop("milestone_ids", None)

        if "cost_type_code" in updates:
            updates["cost_type_code"] = validate_cost_type_code(self.db, updates["cost_type_code"])
            if updates["cost_type_code"] is None:
                raise ValidationError("Cost type cannot be empty.")

        # Resolve the effective cost type + phase after this patch.
        effective_type = updates.get("cost_type_code", row.cost_type_code)
        effective_phase = updates.get("phase", row.phase)
        if effective_type == ONE_TIME:
            updates["phase"] = None
            effective_phase = None
            milestone_ids = []  # one-time clears its bundle
        elif effective_type == FIXED:
            if effective_phase is None:
                raise ValidationError("Phase is required for a fixed cost row.")
            # Must keep at least one milestone (see create) so the phase stays payable.
            effective_ms = milestone_ids if milestone_ids is not None else self.repo.list_milestone_ids(row.id)
            if not effective_ms:
                raise ValidationError("A fixed cost row needs at least one milestone.")
        elif effective_type in EXPENSE_TYPES:
            self._assert_expense_phase(row.project_id, effective_phase, effective_type)
            milestone_ids = []  # standalone expense line — no deliverable binding
            eff_mode = (updates.get("billed_mode", row.billed_mode) or "percent")
            eff_bval = updates.get("billed_value", row.billed_value)
            if eff_bval is None:
                eff_bval = Decimal("100")
            if row.billed_mode is None and "billed_mode" not in updates:
                updates["billed_mode"] = eff_mode
            if row.billed_value is None and "billed_value" not in updates:
                updates["billed_value"] = eff_bval
            self._assert_expense_billed(
                row.project_id, effective_phase, effective_type, eff_mode, eff_bval,
                updates.get("per_transaction_cost", row.per_transaction_cost),
                updates.get("planned_transactions", row.planned_transactions),
                updates.get("cost", row.cost), updates.get("tax_amount", row.tax_amount))

        # Keep the expense-only columns consistent with the effective cost type.
        if effective_type != TRANSACTION_COST and (
            row.per_transaction_cost is not None or row.planned_transactions is not None
            or "per_transaction_cost" in updates or "planned_transactions" in updates
        ):
            updates["per_transaction_cost"] = None
            updates["planned_transactions"] = None
        if effective_type not in EXPENSE_TYPES and (
            row.line_label is not None or "line_label" in updates
        ):
            updates["line_label"] = None
        if effective_type not in EXPENSE_TYPES and (
            row.billed_mode is not None or row.billed_value is not None
            or "billed_mode" in updates or "billed_value" in updates
        ):
            updates["billed_mode"] = None
            updates["billed_value"] = None

        if milestone_ids is not None and milestone_ids:
            self._validate_milestones(row.project_id, milestone_ids)
            self._assert_milestones_free(row.project_id, milestone_ids, exclude_id=row.id)

        if updates:
            before = {k: getattr(row, k) for k in updates}
            try:
                self.repo.update(row, updated_by=caller_user_id, **updates)
                self.db.flush()
            except Exception as exc:  # pragma: no cover
                self.db.rollback()
                raise self._conflict_or_raise(exc, row.project_id)
            self.audit.write(
                project_id=row.project_id, target_kind="cost_item", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={k: {"before": _s(before[k]), "after": _s(updates[k])} for k in updates},
            )

        if milestone_ids is not None:
            self.repo.replace_milestones(row.id, milestone_ids)

        self._reconcile_payment_terms(row.project_id, caller_user_id)
        self.db.commit()
        row._milestone_ids = self.repo.list_milestone_ids(row.id)
        return row

    def delete(self, cost_item_id: str, *, caller_user_id: Optional[str], caller_is_admin: bool = False) -> ProjectCostItem:
        row = self.get_by_id(cost_item_id)
        project = self._require_project(row.project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        self.repo.soft_delete(row)
        self.audit.write(
            project_id=row.project_id, target_kind="cost_item", target_id=row.id,
            action="delete", actor_user_id=caller_user_id,
        )
        self._reconcile_payment_terms(row.project_id, caller_user_id)
        self.db.commit()
        return row

    def restore(self, cost_item_id: str, *, caller_user_id: Optional[str], caller_is_admin: bool = False) -> ProjectCostItem:
        row = self.repo.get_by_id(cost_item_id, include_deleted=True)
        if row is None:
            raise ValidationError("The cost item could not be found.")
        project = self._require_project(row.project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        try:
            self.repo.restore(row)
            self.db.flush()
        except Exception as exc:  # pragma: no cover
            self.db.rollback()
            raise self._conflict_or_raise(exc, row.project_id)
        self.audit.write(
            project_id=row.project_id, target_kind="cost_item", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self._reconcile_payment_terms(row.project_id, caller_user_id)
        self.db.commit()
        row._milestone_ids = self.repo.list_milestone_ids(row.id)
        return row

    # --------------------------------------------------- payment-term sync

    def _reconcile_payment_terms(self, project_id: str, caller_user_id: Optional[str]) -> None:
        """Make the live payment-term rows exactly match the milestones bound
        to the live FIXED cost rows — one row per milestone, carrying its cost
        row (``cost_item_id``, the calc unit) and that row's phase (display).

        Preserves a milestone's entered percent across add → remove → re-add and
        across a phase RENAME, but resets it to null whenever keeping it would
        push the target phase over its 100% cap (a reassign into an already-full
        phase, or a same-phase refill race). This mirrors the per-phase cap the
        direct term-PATCH enforces, so the cap can't be bypassed via cost-item
        edits."""
        binding = self.repo.milestone_cost_binding(project_id)  # {ms: (cost_item_id, phase)}
        eligible = set(binding.keys())

        live_terms = self.payment_terms.list_all_live(project_id)
        live_ms = {t.milestone_id for t in live_terms}

        # Remove terms whose milestone is no longer on a cost row; keep the
        # cost-row / phase stamp current for the rest.
        for term in live_terms:
            if term.milestone_id not in eligible:
                self.payment_terms.soft_delete(term)
                continue
            cost_item_id, phase = binding[term.milestone_id]
            updates = {}
            if term.phase != phase:
                updates["phase"] = phase
                # The percent was allocated within the OLD phase; keep it only if
                # it still fits the NEW phase's 100% headroom, else drop to null.
                if not self._percent_fits_phase(project_id, phase, term.percent_of_payment):
                    updates["percent_of_payment"] = None
            if term.cost_item_id != cost_item_id:
                updates["cost_item_id"] = cost_item_id
            if updates:
                self.payment_terms.update(term, updated_by=caller_user_id, **updates)

        # Add a row for each newly-eligible milestone (restore if one was
        # previously removed, else create a blank row).
        for milestone_id, (cost_item_id, phase) in binding.items():
            if milestone_id in live_ms:
                continue
            dead = self.payment_terms.get_soft_deleted_by_milestone(project_id, milestone_id)
            if dead is not None:
                # Bring it back live with a FRESH position and the current cost
                # row + phase. Keep its saved percent only if it still fits the
                # phase's headroom (guards the same-phase refill race), else null.
                keep_pct = dead.percent_of_payment
                if not self._percent_fits_phase(project_id, phase, keep_pct):
                    keep_pct = None
                self.payment_terms.update(
                    dead, deleted_at=None, phase=phase, cost_item_id=cost_item_id,
                    percent_of_payment=keep_pct,
                    position=self.payment_terms.next_position_for_project(project_id),
                    updated_by=caller_user_id,
                )
            else:
                self.payment_terms.create(
                    project_id=project_id, phase=phase, milestone_id=milestone_id,
                    cost_item_id=cost_item_id,
                    frequency_code=None, percent_of_payment=None,
                    position=self.payment_terms.next_position_for_project(project_id),
                    created_by=caller_user_id, updated_by=caller_user_id,
                )

        self._prune_orphan_phase_config(project_id, caller_user_id)

    def _percent_fits_phase(self, project_id: str, phase, pct) -> bool:
        """True if adding ``pct`` to the phase's current live Σ percent keeps it
        within the 100% cap (mirrors ProjectPaymentTermService's per-phase cap).
        ``None`` percent always fits."""
        if pct is None:
            return True
        others = self.payment_terms.sum_percent_for_phase(project_id, phase)
        return others + Decimal(str(pct)) <= Decimal("100")

    def _prune_orphan_phase_config(self, project_id: str, caller_user_id: Optional[str]) -> None:
        """Soft-delete carry-forward config (project_phase_qrg) + custom
        allocation rows for phases that no longer have any live FIXED cost row.

        A phase EXISTS only while it has cost rows; when it's edited to a new
        name or deleted, its old config/allocation rows must go too — otherwise
        the phase lingers as a phantom on the payment page and a re-created
        same-name phase would silently inherit stale carry-forward settings."""
        live_phases = {
            c.phase for c in self.repo.list_all_live(project_id)
            if c.cost_type_code == FIXED and c.phase is not None
        }
        self.phase_qrg.soft_delete_orphans(project_id, live_phases, actor_user_id=caller_user_id)
        self.cf_allocations.soft_delete_orphans(project_id, live_phases, actor_user_id=caller_user_id)

    # --------------------------------------------------------------- helpers

    def _is_last_phase(self, project_id: str, phase) -> bool:
        """True if ``phase`` is the chronologically LAST phase (same date order the
        payment page uses, over the phases that have fixed cost)."""
        dates = self.repo.phase_milestone_date_bounds(project_id)
        phases = {c.phase for c in self.repo.list_all_live(project_id)
                  if c.cost_type_code == FIXED and c.phase is not None}
        phases.add(phase)
        ordered = order_phases(phases, dates)
        return bool(ordered) and ordered[-1] == phase

    def _assert_expense_billed(self, project_id, phase, cost_type, billed_mode,
                               billed_value, per_txn, planned, cost, tax) -> None:
        """The LAST phase can't carry a remainder forward, so a resource/transaction
        line there must be fully billed (100% / its full value)."""
        if cost_type == TRANSACTION_COST:
            value = Decimal(str(per_txn or 0)) * Decimal(str(planned or 0))
        else:
            value = Decimal(str(cost or 0)) + Decimal(str(tax or 0))
        if (billed_mode or "percent").lower() == "percent":
            billed = value * Decimal(str(billed_value if billed_value is not None else 100)) / Decimal("100")
        else:
            billed = Decimal(str(billed_value or 0))
        if billed < value - Decimal("0.005") and self._is_last_phase(project_id, phase):
            raise ValidationError(
                "On the last phase a resource/transaction cost must be fully billed "
                "(100%) — it has nowhere to carry a remainder forward.")

    def _assert_expense_phase(self, project_id: str, phase, cost_type: str) -> None:
        """Resource / transaction cost may attach ONLY to an existing phase that
        already has fixed (delivery) cost — decision A1, so there are no
        expense-only phases."""
        if phase is None:
            raise ValidationError(f"Phase is required for a {cost_type.replace('_', ' ')} row.")
        has_fixed = any(
            c.phase == phase for c in self.repo.list_all_live(project_id)
            if c.cost_type_code == FIXED
        )
        if not has_fixed:
            raise ValidationError(
                f"A {cost_type.replace('_', ' ')} can only be added to a phase that "
                "already has a fixed (delivery) cost."
            )

    def _require_project(self, project_id: str):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        return project

    def _validate_milestones(self, project_id: str, milestone_ids: List[str]) -> None:
        # Meeting milestones (is_meeting=True) are hidden from milestone-
        # level surfaces and must not be bindable to cost rows — they hold
        # meeting activities, not deliverable scope. Reject any caller that
        # tries to bind a cost item to one.
        live = set(self.db.execute(
            select(Milestone.id)
            .where(Milestone.id.in_(milestone_ids))
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
            .where(Milestone.is_meeting.is_(False))
        ).scalars())
        missing = [m for m in milestone_ids if m not in live]
        if missing:
            raise ValidationError(
                f"Unknown milestone(s) for this project: {', '.join(missing)}"
            )

    def _assert_milestones_free(
        self, project_id: str, milestone_ids: List[str], *, exclude_id: Optional[str],
    ) -> None:
        """A milestone may belong to only ONE live cost row (hence one phase).
        Reject any milestone already bound to a different cost row."""
        conflicts = self.repo.phases_binding_milestones(
            project_id, milestone_ids, exclude_cost_item_id=exclude_id,
        )
        offending = sorted({mid for mid, _ in conflicts})
        if offending:
            raise ValidationError(
                "Milestone(s) already used in another cost row: "
                f"{', '.join(offending)}. A milestone can belong to one cost row only."
            )

    @staticmethod
    def _conflict_or_raise(exc: Exception, project_id: str) -> Exception:
        text = str(getattr(exc, "orig", exc)).lower()
        if "one_time_per_project" in text:
            return ConflictError(
                "This project already has a one-time cost row. Only one is allowed.",
                code="conflict", details={"project_id": project_id},
            )
        if "position" in text:
            return ConflictError(
                "A cost item already exists at that position.",
                code="conflict", details={"project_id": project_id},
            )
        return exc


def _s(value) -> Optional[str]:
    return None if value is None else str(value)
