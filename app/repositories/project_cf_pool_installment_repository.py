"""Data access for project_cf_pool_installment (frequency carry-forward pool).

SQL only. The service owns the "replace the pending set for a phase" semantics:
on each carry-forward save it soft-deletes the phase's live PENDING installments
and inserts the freshly-computed schedule. Installments already ``on_invoice``
are left untouched (invoicing, to be built, freezes those).
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.project_cf_pool_installment import ProjectCfPoolInstallment


class ProjectCfPoolInstallmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all_live(self, project_id: str) -> List[ProjectCfPoolInstallment]:
        return list(self.db.execute(
            select(ProjectCfPoolInstallment)
            .where(ProjectCfPoolInstallment.project_id == project_id)
            .where(ProjectCfPoolInstallment.deleted_at.is_(None))
            .order_by(
                ProjectCfPoolInstallment.source_phase.asc(),
                ProjectCfPoolInstallment.period_index.asc(),
            )
        ).scalars().all())

    def soft_delete_pending_for_phase(
        self, project_id: str, source_phase: str, *, actor_user_id=None,
    ) -> None:
        """Soft-delete every live PENDING installment for one carrying phase
        (invoiced installments are frozen and left untouched)."""
        self.db.execute(
            update(ProjectCfPoolInstallment)
            .where(ProjectCfPoolInstallment.project_id == project_id)
            .where(ProjectCfPoolInstallment.source_phase == source_phase)
            .where(ProjectCfPoolInstallment.deleted_at.is_(None))
            .where(ProjectCfPoolInstallment.status == "pending")
            .values(deleted_at=datetime.utcnow(), updated_by=actor_user_id)
        )
        self.db.flush()

    def replace_pending_for_phase(
        self, project_id: str, source_phase: str, frequency_code: str,
        installments: List[dict], *, actor_user_id=None,
    ) -> List[ProjectCfPoolInstallment]:
        """Soft-delete the phase's live pending installments and insert the fresh
        schedule. Each ``installments`` dict: ``{period_index, period_start,
        period_end, amount}``."""
        self.soft_delete_pending_for_phase(project_id, source_phase, actor_user_id=actor_user_id)
        created: List[ProjectCfPoolInstallment] = []
        for inst in installments:
            row = ProjectCfPoolInstallment(
                project_id=project_id,
                source_phase=source_phase,
                frequency_code=frequency_code,
                period_index=inst["period_index"],
                period_start=inst["period_start"],
                period_end=inst["period_end"],
                amount=inst["amount"],
                status="pending",
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
            self.db.add(row)
            created.append(row)
        self.db.flush()
        return created
