"""ProjectCostItemService — business logic for the "Project Cost" table.

Owns create / update / delete / restore of cost rows plus the milestone
bundle binding. Enforces:
  - publish-lock (admin bypass) via app.utilities.payment_lock
  - cost_type_code resolves to an active master (cross-schema mirror)
  - one-time rows carry no phase / no milestones, and only one live one-time
    row per project
  - bound milestones belong to the project (live) and a milestone stays in a
    single phase across the project
Transactions commit once at the end. Derived ``total`` is computed in the
controller (payment_calc); the service returns the ORM row.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ProjectNotFoundError, ValidationError
from app.models.milestone import Milestone
from app.models.project_cost_item import ProjectCostItem
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_cost_item_repository import ProjectCostItemRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.payment import CostItemCreateRequest, CostItemUpdateRequest
from app.utilities.payment_lock import assert_payment_writable
from app.utilities.payment_masters import validate_cost_type_code

ONE_TIME = "one_time"


class ProjectCostItemService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectCostItemRepository(db)
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

    # ----------------------------------------------------------------- write

    def create(
        self, project_id: str, payload: CostItemCreateRequest, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> ProjectCostItem:
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        cost_type = validate_cost_type_code(self.db, payload.cost_type_code)
        phase = payload.phase
        milestone_ids = list(payload.milestone_ids or [])

        # One-time is a single deliverable: no phase, no milestones.
        if cost_type == ONE_TIME:
            phase = None
            milestone_ids = []

        if milestone_ids:
            self._validate_milestones(project_id, milestone_ids)
            self._assert_one_phase_per_milestone(project_id, milestone_ids, phase, exclude_id=None)

        position = (
            payload.position if payload.position is not None and payload.position > 0
            else self.repo.next_position_for_project(project_id)
        )

        try:
            row = self.repo.create(
                project_id=project_id,
                cost_type_code=cost_type,
                phase=phase,
                cost=payload.cost,
                tax_percent=payload.tax_percent,
                position=position,
                created_by=caller_user_id,
                updated_by=caller_user_id,
            )
            self.db.flush()
        except Exception as exc:  # pragma: no cover - surfaced as friendly 409
            self.db.rollback()
            raise self._one_time_conflict_or_raise(exc, project_id)

        if milestone_ids:
            self.repo.replace_milestones(row.id, milestone_ids)

        self.audit.write(
            project_id=project_id, target_kind="cost_item", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"cost_type_code": cost_type, "phase": phase},
        )
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

        # Resolve the effective cost type + phase after this patch.
        effective_type = updates.get("cost_type_code", row.cost_type_code)
        effective_phase = updates.get("phase", row.phase)
        if effective_type == ONE_TIME:
            updates["phase"] = None
            effective_phase = None
            milestone_ids = []  # one-time clears its bundle

        if milestone_ids is not None and milestone_ids:
            self._validate_milestones(row.project_id, milestone_ids)
            self._assert_one_phase_per_milestone(
                row.project_id, milestone_ids, effective_phase, exclude_id=row.id,
            )

        if updates:
            before = {k: getattr(row, k) for k in updates}
            try:
                self.repo.update(row, updated_by=caller_user_id, **updates)
                self.db.flush()
            except Exception as exc:  # pragma: no cover
                self.db.rollback()
                raise self._one_time_conflict_or_raise(exc, row.project_id)
            self.audit.write(
                project_id=row.project_id, target_kind="cost_item", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={k: {"before": _s(before[k]), "after": _s(updates[k])} for k in updates},
            )

        if milestone_ids is not None:
            self.repo.replace_milestones(row.id, milestone_ids)

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
        self.db.commit()
        return row

    def restore(self, cost_item_id: str, *, caller_user_id: Optional[str], caller_is_admin: bool = False) -> ProjectCostItem:
        row = self.repo.get_by_id(cost_item_id, include_deleted=True)
        if row is None:
            raise ValidationError("The cost item could not be found.")
        project = self._require_project(row.project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        self.repo.restore(row)
        self.audit.write(
            project_id=row.project_id, target_kind="cost_item", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        row._milestone_ids = self.repo.list_milestone_ids(row.id)
        return row

    # --------------------------------------------------------------- helpers

    def _require_project(self, project_id: str):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        return project

    def _validate_milestones(self, project_id: str, milestone_ids: List[str]) -> None:
        live = set(self.db.execute(
            select(Milestone.id)
            .where(Milestone.id.in_(milestone_ids))
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
        ).scalars())
        missing = [m for m in milestone_ids if m not in live]
        if missing:
            raise ValidationError(
                f"Unknown milestone(s) for this project: {', '.join(missing)}"
            )

    def _assert_one_phase_per_milestone(
        self, project_id: str, milestone_ids: List[str], phase: Optional[int], *, exclude_id: Optional[str],
    ) -> None:
        if phase is None:
            return
        conflicts = self.repo.phases_binding_milestones(
            project_id, milestone_ids, exclude_cost_item_id=exclude_id,
        )
        offending = [mid for mid, other_phase in conflicts if other_phase is not None and other_phase != phase]
        if offending:
            raise ValidationError(
                "Milestone(s) already bound to a different phase: "
                f"{', '.join(sorted(set(offending)))}. A milestone belongs to one phase only."
            )

    @staticmethod
    def _one_time_conflict_or_raise(exc: Exception, project_id: str) -> Exception:
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
