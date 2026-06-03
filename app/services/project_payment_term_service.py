"""ProjectPaymentTermService — business logic for the "Project Term" table.

Owns create / update / delete / restore of payment-term rows. Enforces:
  - publish-lock (admin bypass)
  - frequency_code resolves to an active master (cross-schema mirror)
  - milestone belongs to the project (live) and is paid out once
Derived ``value`` (percent × phase fixed total) is computed in the
controller / page builder (payment_calc). The service returns the ORM row.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ProjectNotFoundError, ValidationError
from app.models.milestone import Milestone
from app.models.project_payment_term import ProjectPaymentTerm
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_payment_term_repository import ProjectPaymentTermRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.payment import PaymentTermCreateRequest, PaymentTermUpdateRequest
from app.utilities.payment_lock import assert_payment_writable
from app.utilities.payment_masters import validate_frequency_code


class ProjectPaymentTermService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectPaymentTermRepository(db)
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

    def create(
        self, project_id: str, payload: PaymentTermCreateRequest, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> ProjectPaymentTerm:
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        frequency = validate_frequency_code(self.db, payload.frequency_code)
        if payload.milestone_id:
            self._validate_milestone(project_id, payload.milestone_id)

        position = (
            payload.position if payload.position is not None and payload.position > 0
            else self.repo.next_position_for_project(project_id)
        )

        try:
            row = self.repo.create(
                project_id=project_id,
                phase=payload.phase,
                milestone_id=payload.milestone_id,
                frequency_code=frequency,
                percent_of_payment=payload.percent_of_payment,
                position=position,
                created_by=caller_user_id,
                updated_by=caller_user_id,
            )
            self.db.flush()
        except Exception as exc:  # pragma: no cover
            self.db.rollback()
            raise self._conflict_or_raise(exc, project_id)

        self.audit.write(
            project_id=project_id, target_kind="payment_term", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"phase": payload.phase, "milestone_id": payload.milestone_id},
        )
        self.db.commit()
        return row

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
        if "milestone_id" in updates and updates["milestone_id"]:
            self._validate_milestone(row.project_id, updates["milestone_id"])

        before = {k: getattr(row, k) for k in updates}
        try:
            self.repo.update(row, updated_by=caller_user_id, **updates)
            self.db.flush()
        except Exception as exc:  # pragma: no cover
            self.db.rollback()
            raise self._conflict_or_raise(exc, row.project_id)

        self.audit.write(
            project_id=row.project_id, target_kind="payment_term", target_id=row.id,
            action="update", actor_user_id=caller_user_id,
            changes={k: {"before": _s(before[k]), "after": _s(updates[k])} for k in updates},
        )
        self.db.commit()
        return row

    def delete(self, term_id: str, *, caller_user_id: Optional[str], caller_is_admin: bool = False) -> ProjectPaymentTerm:
        row = self.get_by_id(term_id)
        project = self._require_project(row.project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        self.repo.soft_delete(row)
        self.audit.write(
            project_id=row.project_id, target_kind="payment_term", target_id=row.id,
            action="delete", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def restore(self, term_id: str, *, caller_user_id: Optional[str], caller_is_admin: bool = False) -> ProjectPaymentTerm:
        row = self.repo.get_by_id(term_id, include_deleted=True)
        if row is None:
            raise ValidationError("The payment term could not be found.")
        project = self._require_project(row.project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        try:
            self.repo.restore(row)
            self.db.flush()
        except Exception as exc:  # pragma: no cover
            self.db.rollback()
            raise self._conflict_or_raise(exc, row.project_id)
        self.audit.write(
            project_id=row.project_id, target_kind="payment_term", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    # --------------------------------------------------------------- helpers

    def _require_project(self, project_id: str):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        return project

    def _validate_milestone(self, project_id: str, milestone_id: str) -> None:
        found = self.db.execute(
            select(Milestone.id)
            .where(Milestone.id == milestone_id)
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
            .limit(1)
        ).first()
        if found is None:
            raise ValidationError(
                f"Unknown milestone for this project: {milestone_id}"
            )

    @staticmethod
    def _conflict_or_raise(exc: Exception, project_id: str) -> Exception:
        text = str(getattr(exc, "orig", exc)).lower()
        if "project_milestone" in text:
            return ConflictError(
                "This milestone already has a payment term. A milestone is paid out once.",
                code="conflict", details={"project_id": project_id},
            )
        if "position" in text:
            return ConflictError(
                "A payment term already exists at that position.",
                code="conflict", details={"project_id": project_id},
            )
        return exc


def _s(value) -> Optional[str]:
    return None if value is None else str(value)
