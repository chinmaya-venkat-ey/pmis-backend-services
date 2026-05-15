"""ActivityController."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.repositories.activity_repository import ActivityRepository
from app.schemas.activity import (
    ActivityCreateRequest,
    ActivityResourceSchema,
    ActivityResponse,
    ActivityUpdateRequest,
)
from app.services.activity_service import ActivityService


class ActivityController:
    def __init__(self, db: Session):
        self.db = db
        self.service = ActivityService(db)
        self.repo = ActivityRepository(db)

    def _to_response(self, row) -> ActivityResponse:
        resp = ActivityResponse.model_validate(row)
        resp.depends_on = self.repo.list_dependencies_for(row.id)
        resource_row = self.repo.get_resource(row.id)
        resp.resource = ActivityResourceSchema.model_validate(resource_row) if resource_row else None
        return resp

    def get(self, activity_id: str) -> ActivityResponse:
        return self._to_response(self.service.get_by_id(activity_id))

    def list_for_milestone(self, milestone_id: str, *, offset=1, page_size=50, include_deleted=False):
        rows, total = self.service.list_for_milestone(
            milestone_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )
        return {
            "items": [self._to_response(r) for r in rows],
            "total": total, "offset": offset, "page_size": page_size,
        }

    def create(self, payload: ActivityCreateRequest, *, caller_user_id: Optional[str]):
        row = self.service.create(payload, caller_user_id=caller_user_id)
        return self._to_response(row)

    def update(self, activity_id: str, payload: ActivityUpdateRequest, *, caller_user_id: Optional[str], request=None):
        row = self.service.update(activity_id, payload, caller_user_id=caller_user_id, request=request)
        return self._to_response(row)

    def delete(self, activity_id: str, *, caller_user_id: Optional[str]):
        row = self.service.delete(activity_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def restore(self, activity_id: str, *, caller_user_id: Optional[str]):
        row = self.service.restore(activity_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def replace_dependencies(self, activity_id: str, depends_on_ids: List[str], *, caller_user_id: Optional[str]):
        row, _ = self.service.replace_dependencies(activity_id, depends_on_ids, caller_user_id=caller_user_id)
        return self._to_response(row)
