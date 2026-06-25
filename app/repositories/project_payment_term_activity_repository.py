"""Data access for project_payment_term_activities (per-activity term split).

SQL only. The service replaces the whole set for a term in one call, so this
exposes list + a wholesale soft-replace alongside plain CRUD.
"""
from __future__ import annotations

from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_payment_term_activity import ProjectPaymentTermActivity
from app.utilities.timezones import now_ist


class ProjectPaymentTermActivityRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_term(self, payment_term_id: str) -> List[ProjectPaymentTermActivity]:
        return list(self.db.execute(
            select(ProjectPaymentTermActivity)
            .where(ProjectPaymentTermActivity.payment_term_id == payment_term_id)
            .where(ProjectPaymentTermActivity.deleted_at.is_(None))
            .order_by(ProjectPaymentTermActivity.created_at.asc())
        ).scalars().all())

    def list_for_terms(
        self, payment_term_ids: List[str],
    ) -> Dict[str, List[ProjectPaymentTermActivity]]:
        """Bulk: ``{payment_term_id: [rows...]}`` for the given terms (live)."""
        out: Dict[str, List[ProjectPaymentTermActivity]] = {}
        if not payment_term_ids:
            return out
        rows = self.db.execute(
            select(ProjectPaymentTermActivity)
            .where(ProjectPaymentTermActivity.payment_term_id.in_(payment_term_ids))
            .where(ProjectPaymentTermActivity.deleted_at.is_(None))
            .order_by(ProjectPaymentTermActivity.created_at.asc())
        ).scalars().all()
        for r in rows:
            out.setdefault(r.payment_term_id, []).append(r)
        return out

    def replace_for_term(
        self, *, project_id: str, payment_term_id: str,
        allocations: List[dict], caller_user_id: str = None,
    ) -> List[ProjectPaymentTermActivity]:
        """Soft-delete the term's current live rows and insert the new set.

        ``allocations`` = ``[{"activity_id": str, "percent_of_payment": Decimal}]``.
        """
        ts = now_ist()
        for existing in self.list_for_term(payment_term_id):
            existing.deleted_at = ts
            existing.updated_by = caller_user_id
        new_rows: List[ProjectPaymentTermActivity] = []
        for alloc in allocations:
            row = ProjectPaymentTermActivity(
                project_id=project_id,
                payment_term_id=payment_term_id,
                activity_id=alloc["activity_id"],
                percent_of_payment=alloc.get("percent_of_payment"),
                created_by=caller_user_id,
                updated_by=caller_user_id,
            )
            self.db.add(row)
            new_rows.append(row)
        self.db.flush()
        return new_rows
