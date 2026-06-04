"""Data access for project_cost_items + the cost_item_milestones M:N.

SQL only — no business rules. Soft-delete via ``deleted_at`` (default
filter excludes deleted). The milestone binding is replaced wholesale.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.cost_item_milestone import CostItemMilestone
from app.models.project_cost_item import ProjectCostItem


class ProjectCostItemRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, cost_item_id: str, *, include_deleted: bool = False) -> Optional[ProjectCostItem]:
        stmt = select(ProjectCostItem).where(ProjectCostItem.id == cost_item_id)
        if not include_deleted:
            stmt = stmt.where(ProjectCostItem.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_project(
        self, project_id: str, *, offset: int = 1, page_size: int = 50,
        include_deleted: bool = False,
    ) -> Tuple[List[ProjectCostItem], int]:
        clauses = [ProjectCostItem.project_id == project_id]
        if not include_deleted:
            clauses.append(ProjectCostItem.deleted_at.is_(None))
        stmt = select(ProjectCostItem).where(and_(*clauses)).order_by(ProjectCostItem.position.asc())
        count_stmt = select(func.count()).select_from(ProjectCostItem).where(and_(*clauses))
        total = self.db.execute(count_stmt).scalar_one()
        rows = self.db.execute(
            stmt.offset(max(0, offset - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def list_all_live(self, project_id: str) -> List[ProjectCostItem]:
        """Every live cost row for the project (no pagination) — used by the
        calc/aggregation paths."""
        return list(self.db.execute(
            select(ProjectCostItem)
            .where(ProjectCostItem.project_id == project_id)
            .where(ProjectCostItem.deleted_at.is_(None))
            .order_by(ProjectCostItem.position.asc())
        ).scalars().all())

    def next_position_for_project(self, project_id: str) -> int:
        row = self.db.execute(
            select(func.coalesce(func.max(ProjectCostItem.position), 0))
            .where(ProjectCostItem.project_id == project_id)
            .where(ProjectCostItem.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def create(self, **kwargs) -> ProjectCostItem:
        row = ProjectCostItem(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: ProjectCostItem, **kwargs) -> ProjectCostItem:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def soft_delete(self, row: ProjectCostItem) -> ProjectCostItem:
        from app.utilities.timezones import now_ist
        row.deleted_at = now_ist()
        self.db.flush()
        return row

    def restore(self, row: ProjectCostItem) -> ProjectCostItem:
        row.deleted_at = None
        self.db.flush()
        return row

    # ----------------------------------------------------- milestone binding

    def list_milestone_ids(self, cost_item_id: str) -> List[str]:
        return list(self.db.execute(
            select(CostItemMilestone.milestone_id)
            .where(CostItemMilestone.cost_item_id == cost_item_id)
        ).scalars())

    def replace_milestones(self, cost_item_id: str, milestone_ids: List[str]) -> None:
        self.db.execute(
            CostItemMilestone.__table__.delete().where(
                CostItemMilestone.cost_item_id == cost_item_id
            )
        )
        for mid in milestone_ids:
            self.db.add(CostItemMilestone(cost_item_id=cost_item_id, milestone_id=mid))
        self.db.flush()

    def phases_binding_milestones(
        self, project_id: str, milestone_ids: List[str], *, exclude_cost_item_id: Optional[str] = None,
    ) -> List[Tuple[str, int]]:
        """Return (milestone_id, phase) for LIVE cost items in this project
        that already bind any of ``milestone_ids`` — used to enforce
        one-phase-per-milestone. Optionally exclude the cost item being
        updated."""
        if not milestone_ids:
            return []
        stmt = (
            select(CostItemMilestone.milestone_id, ProjectCostItem.phase)
            .join(ProjectCostItem, ProjectCostItem.id == CostItemMilestone.cost_item_id)
            .where(ProjectCostItem.project_id == project_id)
            .where(ProjectCostItem.deleted_at.is_(None))
            .where(CostItemMilestone.milestone_id.in_(milestone_ids))
        )
        if exclude_cost_item_id is not None:
            stmt = stmt.where(ProjectCostItem.id != exclude_cost_item_id)
        return [(mid, phase) for mid, phase in self.db.execute(stmt).all()]

    def milestone_ids_by_cost_item(self, cost_item_ids: List[str]) -> dict:
        """Bulk map cost_item_id → [milestone_id] for the aggregation path."""
        if not cost_item_ids:
            return {}
        rows = self.db.execute(
            select(CostItemMilestone.cost_item_id, CostItemMilestone.milestone_id)
            .where(CostItemMilestone.cost_item_id.in_(cost_item_ids))
        ).all()
        out: dict = {}
        for cid, mid in rows:
            out.setdefault(cid, []).append(mid)
        return out

    def milestone_phase_map(self, project_id: str) -> dict:
        """Return ``{milestone_id: phase}`` for every milestone bound to a
        LIVE FIXED cost row (with a phase) in this project. A milestone is in
        exactly one phase (enforced), so the map is well-defined. This drives
        the payment-term auto-sync (rows exist only for these milestones)."""
        rows = self.db.execute(
            select(CostItemMilestone.milestone_id, ProjectCostItem.phase)
            .join(ProjectCostItem, ProjectCostItem.id == CostItemMilestone.cost_item_id)
            .where(ProjectCostItem.project_id == project_id)
            .where(ProjectCostItem.deleted_at.is_(None))
            .where(ProjectCostItem.cost_type_code == "fixed")
            .where(ProjectCostItem.phase.is_not(None))
        ).all()
        return dict(rows)

    def milestone_cost_binding(self, project_id: str) -> dict:
        """Return ``{milestone_id: (cost_item_id, phase)}`` for every milestone
        bound to a LIVE FIXED cost row in this project. A milestone is in
        exactly one cost row (enforced), so the map is well-defined. Drives the
        payment-term auto-sync (one row per milestone, carrying its cost row +
        phase)."""
        rows = self.db.execute(
            select(
                CostItemMilestone.milestone_id,
                CostItemMilestone.cost_item_id,
                ProjectCostItem.phase,
            )
            .join(ProjectCostItem, ProjectCostItem.id == CostItemMilestone.cost_item_id)
            .where(ProjectCostItem.project_id == project_id)
            .where(ProjectCostItem.deleted_at.is_(None))
            .where(ProjectCostItem.cost_type_code == "fixed")
        ).all()
        return {mid: (cid, phase) for mid, cid, phase in rows}

    def is_milestone_bound(self, milestone_id: str) -> bool:
        """True if the milestone is bound to ANY live cost row (i.e. it's on
        the finance page). Used to block milestone deletion."""
        found = self.db.execute(
            select(CostItemMilestone.milestone_id)
            .join(ProjectCostItem, ProjectCostItem.id == CostItemMilestone.cost_item_id)
            .where(CostItemMilestone.milestone_id == milestone_id)
            .where(ProjectCostItem.deleted_at.is_(None))
            .limit(1)
        ).first()
        return found is not None

    def bound_milestone_ids(
        self, project_id: str, *, exclude_cost_item_id: Optional[str] = None,
    ) -> set:
        """Every milestone id already bound to a LIVE cost row in this project.
        Optionally exclude one cost row (the one being edited) so its own
        milestones stay selectable. Drives the "available milestones" picker."""
        stmt = (
            select(CostItemMilestone.milestone_id)
            .join(ProjectCostItem, ProjectCostItem.id == CostItemMilestone.cost_item_id)
            .where(ProjectCostItem.project_id == project_id)
            .where(ProjectCostItem.deleted_at.is_(None))
        )
        if exclude_cost_item_id is not None:
            stmt = stmt.where(ProjectCostItem.id != exclude_cost_item_id)
        return set(self.db.execute(stmt).scalars())
