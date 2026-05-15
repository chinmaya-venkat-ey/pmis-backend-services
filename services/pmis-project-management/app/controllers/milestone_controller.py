"""MilestoneController."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.repositories.milestone_repository import MilestoneRepository
from app.schemas.milestone import (
    MilestoneCreateRequest,
    MilestoneResponse,
    MilestoneUpdateRequest,
)
from app.services.milestone_service import MilestoneService


class MilestoneController:
    def __init__(self, db: Session):
        self.db = db
        self.service = MilestoneService(db)
        self.repo = MilestoneRepository(db)

    def _to_response(self, row) -> MilestoneResponse:
        resp = MilestoneResponse.model_validate(row)
        resp.depends_on = self.repo.list_dependencies_for(row.id)
        resp.vendor_ids = self.repo.list_vendors_for(row.id)
        return resp

    def get(self, milestone_id: str) -> MilestoneResponse:
        return self._to_response(self.service.get_by_id(milestone_id))

    def list_for_project(self, project_id: str, *, offset=1, page_size=50, include_deleted=False):
        rows, total = self.service.list_for_project(
            project_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )
        return {
            "items": [self._to_response(r) for r in rows],
            "total": total, "offset": offset, "page_size": page_size,
        }

    def create(self, project_id: str, payload: MilestoneCreateRequest, *, caller_user_id: Optional[str]) -> MilestoneResponse:
        row = self.service.create(project_id, payload, caller_user_id=caller_user_id)
        return self._to_response(row)

    def update(self, milestone_id: str, payload: MilestoneUpdateRequest, *, caller_user_id: Optional[str], request=None) -> MilestoneResponse:
        row = self.service.update(milestone_id, payload, caller_user_id=caller_user_id, request=request)
        return self._to_response(row)

    def delete(self, milestone_id: str, *, caller_user_id: Optional[str]) -> MilestoneResponse:
        row = self.service.delete(milestone_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def restore(self, milestone_id: str, *, caller_user_id: Optional[str]) -> MilestoneResponse:
        row = self.service.restore(milestone_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def replace_dependencies(self, milestone_id: str, depends_on_ids: List[str], *, caller_user_id: Optional[str]):
        row, _ = self.service.replace_dependencies(milestone_id, depends_on_ids, caller_user_id=caller_user_id)
        return self._to_response(row)

    def set_vendors(self, milestone_id: str, vendor_ids: List[str], *, caller_user_id: Optional[str]):
        row, _ = self.service.set_vendors(milestone_id, vendor_ids, caller_user_id=caller_user_id)
        return self._to_response(row)
