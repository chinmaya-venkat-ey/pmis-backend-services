"""PlannedResourceController — HTTP adapter for /planned-resources routes."""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.schemas.planned_resource import (
    PlannedResourceCreateRequest,
    PlannedResourceResponse,
    PlannedResourceUpdateRequest,
)
from app.services.planned_resource_service import PlannedResourceService


class PlannedResourceController:
    def __init__(self, db: Session):
        self.db = db
        self.service = PlannedResourceService(db)

    def list_for_project(self, project_id: str) -> List[PlannedResourceResponse]:
        rows = self.service.list_for_project(project_id)
        return [PlannedResourceResponse.model_validate(r) for r in rows]

    def create(
        self, project_id: str, payload, *, caller_user_id, caller_is_admin=False,
    ) -> PlannedResourceResponse:
        row = self.service.create(
            project_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return PlannedResourceResponse.model_validate(row)

    def get(self, row_id: str) -> PlannedResourceResponse:
        return PlannedResourceResponse.model_validate(self.service.get_by_id(row_id))

    def update(
        self, row_id: str, payload, *, caller_user_id, caller_is_admin=False,
    ) -> PlannedResourceResponse:
        row = self.service.update(
            row_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return PlannedResourceResponse.model_validate(row)

    def delete(self, row_id: str, *, caller_user_id, caller_is_admin=False) -> None:
        self.service.delete(row_id, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin)
