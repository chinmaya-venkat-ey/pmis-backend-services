"""TaskController."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.repositories.task_repository import TaskRepository
from app.schemas.task import (
    TaskCreateRequest,
    TaskResourceSchema,
    TaskResponse,
    TaskUpdateRequest,
)
from app.services.task_service import TaskService


class TaskController:
    def __init__(self, db: Session):
        self.db = db
        self.service = TaskService(db)
        self.repo = TaskRepository(db)

    def _to_response(self, row) -> TaskResponse:
        resp = TaskResponse.model_validate(row)
        resp.depends_on = self.repo.list_dependencies_for(row.id)
        resource_row = self.repo.get_resource(row.id)
        resp.resource = TaskResourceSchema.model_validate(resource_row) if resource_row else None
        return resp

    def get(self, task_id: str) -> TaskResponse:
        return self._to_response(self.service.get_by_id(task_id))

    def list_for_activity(self, activity_id: str, *, offset=1, page_size=50, include_deleted=False):
        rows, total = self.service.list_for_activity(
            activity_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )
        return {
            "items": [self._to_response(r) for r in rows],
            "total": total, "offset": offset, "page_size": page_size,
        }

    def create(self, payload: TaskCreateRequest, *, caller_user_id: Optional[str]):
        row = self.service.create(payload, caller_user_id=caller_user_id)
        return self._to_response(row)

    def update(self, task_id: str, payload: TaskUpdateRequest, *, caller_user_id: Optional[str], request=None):
        row = self.service.update(task_id, payload, caller_user_id=caller_user_id, request=request)
        return self._to_response(row)

    def delete(self, task_id: str, *, caller_user_id: Optional[str]):
        row = self.service.delete(task_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def restore(self, task_id: str, *, caller_user_id: Optional[str]):
        row = self.service.restore(task_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def replace_dependencies(self, task_id: str, depends_on_ids: List[str], *, caller_user_id: Optional[str]):
        row, _ = self.service.replace_dependencies(task_id, depends_on_ids, caller_user_id=caller_user_id)
        return self._to_response(row)
