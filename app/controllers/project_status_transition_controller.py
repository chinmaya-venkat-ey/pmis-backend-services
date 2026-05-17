"""ProjectStatusTransitionController — HTTP adapter for /masters/project-status-transitions/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.project_status_transition import (
    ProjectStatusTransitionCreateRequest,
    ProjectStatusTransitionResponse,
    ProjectStatusTransitionUpdateRequest,
)
from app.services.project_status_transition_service import (
    ProjectStatusTransitionService,
)


class ProjectStatusTransitionController:
    def __init__(self, service: ProjectStatusTransitionService):
        self.service = service

    def list_(
        self, *, include_inactive: bool = False
    ) -> List[ProjectStatusTransitionResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [ProjectStatusTransitionResponse.model_validate(r) for r in rows]

    def get_details(self, row_id: int) -> ProjectStatusTransitionResponse:
        return ProjectStatusTransitionResponse.model_validate(
            self.service.get_by_id(row_id)
        )

    def create(
        self, payload: ProjectStatusTransitionCreateRequest
    ) -> ProjectStatusTransitionResponse:
        return ProjectStatusTransitionResponse.model_validate(
            self.service.create(payload)
        )

    def update(
        self, row_id: int, payload: ProjectStatusTransitionUpdateRequest
    ) -> ProjectStatusTransitionResponse:
        return ProjectStatusTransitionResponse.model_validate(
            self.service.update(row_id, payload)
        )

    def delete(self, row_id: int) -> ProjectStatusTransitionResponse:
        return ProjectStatusTransitionResponse.model_validate(
            self.service.delete(row_id)
        )

    def restore(self, row_id: int) -> ProjectStatusTransitionResponse:
        return ProjectStatusTransitionResponse.model_validate(
            self.service.restore(row_id)
        )
