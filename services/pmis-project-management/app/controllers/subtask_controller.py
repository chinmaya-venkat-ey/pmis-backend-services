"""SubtaskController."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.repositories.subtask_repository import SubtaskRepository
from app.schemas.subtask import (
    SubtaskCreateRequest,
    SubtaskResourceSchema,
    SubtaskResponse,
    SubtaskUpdateRequest,
)
from app.services.subtask_service import SubtaskService


class SubtaskController:
    def __init__(self, db: Session):
        self.db = db
        self.service = SubtaskService(db)
        self.repo = SubtaskRepository(db)

    def _to_response(self, row) -> SubtaskResponse:
        resp = SubtaskResponse.model_validate(row)
        resp.depends_on = self.repo.list_dependencies_for(row.id)
        resource_row = self.repo.get_resource(row.id)
        resp.resource = SubtaskResourceSchema.model_validate(resource_row) if resource_row else None
        return resp

    def get(self, subtask_id: str) -> SubtaskResponse:
        return self._to_response(self.service.get_by_id(subtask_id))

    def list_for_task(self, task_id: str, *, offset=1, page_size=100, include_deleted=False, top_level_only=False):
        rows, total = self.service.list_for_task(
            task_id, offset=offset, page_size=page_size,
            include_deleted=include_deleted, top_level_only=top_level_only,
        )
        return {
            "items": [self._to_response(r) for r in rows],
            "total": total, "offset": offset, "page_size": page_size,
        }

    def create(self, payload: SubtaskCreateRequest, *, caller_user_id: Optional[str]):
        row = self.service.create(payload, caller_user_id=caller_user_id)
        return self._to_response(row)

    def update(self, subtask_id: str, payload: SubtaskUpdateRequest, *, caller_user_id: Optional[str], request=None):
        row = self.service.update(subtask_id, payload, caller_user_id=caller_user_id, request=request)
        return self._to_response(row)

    def delete(self, subtask_id: str, *, caller_user_id: Optional[str]):
        row = self.service.delete(subtask_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def restore(self, subtask_id: str, *, caller_user_id: Optional[str]):
        row = self.service.restore(subtask_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def replace_dependencies(self, subtask_id: str, depends_on_ids: List[str], *, caller_user_id: Optional[str]):
        row, _ = self.service.replace_dependencies(subtask_id, depends_on_ids, caller_user_id=caller_user_id)
        return self._to_response(row)
