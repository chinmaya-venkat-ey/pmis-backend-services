"""Lightweight per-phase summary — date span + delivery-model flags — without
the heavy payment-page computation. Backs GET /api/v3/projects/{uuid}/phases."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.repositories.project_cost_item_repository import ProjectCostItemRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.phase import ProjectPhasesResponse, ProjectPhaseSummary


class PhaseSummaryService:
    def __init__(self, db: Session):
        self.db = db
        self.cost_items = ProjectCostItemRepository(db)
        self.projects = ProjectRepository(db)

    def list_phases(self, project_id: str) -> ProjectPhasesResponse:
        if self.projects.get_by_id(project_id) is None:
            raise NotFoundError(f"Project {project_id} not found.")
        rows = self.cost_items.phase_summaries(project_id)
        # Chronological: earliest-starting phase first (nulls last), then phase id.
        rows = sorted(rows, key=lambda r: (r[1] is None, r[1], str(r[0])))
        phases = [
            ProjectPhaseSummary(
                phase=phase, start_date=start, end_date=end,
                is_resource_based=rb, is_transaction_based=tb,
            )
            for phase, start, end, rb, tb in rows
        ]
        return ProjectPhasesResponse(phases=phases)
