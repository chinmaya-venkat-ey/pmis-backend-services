"""Business logic for the project_status_transitions catalog.

Keyed by id (auto-incrementing surrogate). Edges are unique on
(from_status, to_status) — DB constraint enforces; service surfaces a
friendly conflict error pre-flight.
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import CatalogEntryConflictError, CatalogEntryNotFoundError
from app.models.project_status_transition import ProjectStatusTransition
from app.repositories.project_status_transition_repository import (
    ProjectStatusTransitionRepository,
)
from app.schemas.project_status_transition import (
    ProjectStatusTransitionCreateRequest,
    ProjectStatusTransitionUpdateRequest,
)


class ProjectStatusTransitionService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectStatusTransitionRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[ProjectStatusTransition]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_id(self, row_id: int) -> ProjectStatusTransition:
        row = self.repo.get_by_id(row_id)
        if row is None:
            raise CatalogEntryNotFoundError(
                f"ProjectStatusTransition {row_id!r} not found"
            )
        return row

    def create(
        self, payload: ProjectStatusTransitionCreateRequest
    ) -> ProjectStatusTransition:
        if self.repo.get_by_edge(payload.from_status, payload.to_status) is not None:
            raise CatalogEntryConflictError(
                f"Transition {payload.from_status!r} -> {payload.to_status!r} already exists",
                details={
                    "from_status": payload.from_status,
                    "to_status": payload.to_status,
                },
            )
        row = self.repo.create(
            from_status=payload.from_status,
            to_status=payload.to_status,
            requires_admin=payload.requires_admin,
            active=payload.active,
            description=payload.description,
        )
        self.db.commit()
        return row

    def update(
        self, row_id: int, payload: ProjectStatusTransitionUpdateRequest
    ) -> ProjectStatusTransition:
        row = self.get_by_id(row_id)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, row_id: int) -> ProjectStatusTransition:
        row = self.get_by_id(row_id)
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, row_id: int) -> ProjectStatusTransition:
        row = self.get_by_id(row_id)
        self.repo.reactivate(row)
        self.db.commit()
        return row
