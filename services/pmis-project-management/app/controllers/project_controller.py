"""ProjectController — orchestrates ProjectService + attaches vendor_ids."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.repositories.project_repository import ProjectRepository
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectStatusTransitionRequest,
    ProjectUpdateRequest,
)
from app.services.project_service import ProjectService


class ProjectController:
    def __init__(self, db: Session):
        self.db = db
        self.service = ProjectService(db)
        self.repo = ProjectRepository(db)

    def _to_response(self, row) -> ProjectResponse:
        resp = ProjectResponse.model_validate(row)
        resp.vendor_ids = self.repo.list_vendors_for_project(row.id)
        return resp

    def get(self, project_id: str) -> ProjectResponse:
        return self._to_response(self.service.get_by_id(project_id))

    def list_(
        self, *,
        offset: int = 1, page_size: int = 20,
        status: Optional[str] = None, include_deleted: bool = False,
        caller_user_id: Optional[str] = None, caller_is_admin: bool = False,
    ):
        rows, total = self.service.list_(
            offset=offset, page_size=page_size, status=status,
            include_deleted=include_deleted,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return {
            "items": [self._to_response(r) for r in rows],
            "total": total,
            "offset": offset,
            "page_size": page_size,
        }

    def create(self, payload: ProjectCreateRequest, *, caller_user_id: Optional[str]) -> ProjectResponse:
        row = self.service.create(payload, caller_user_id=caller_user_id)
        return self._to_response(row)

    def update(self, project_id: str, payload: ProjectUpdateRequest, *, caller_user_id: Optional[str], request=None) -> ProjectResponse:
        row = self.service.update(project_id, payload, caller_user_id=caller_user_id, request=request)
        return self._to_response(row)

    def delete(self, project_id: str, *, caller_user_id: Optional[str]) -> ProjectResponse:
        row = self.service.delete(project_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def restore(self, project_id: str, *, caller_user_id: Optional[str]) -> ProjectResponse:
        row = self.service.restore(project_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def transition_status(
        self, project_id: str, payload: ProjectStatusTransitionRequest,
        *, caller_user_id: Optional[str], caller_is_admin: bool,
        request=None,
    ) -> ProjectResponse:
        row = self.service.transition_status(
            project_id, payload,
            caller_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
            request=request,
        )
        return self._to_response(row)

    def set_vendors(self, project_id: str, vendor_ids: List[str], *, caller_user_id: Optional[str]) -> ProjectResponse:
        row = self.service.set_vendors(project_id, vendor_ids, caller_user_id=caller_user_id)
        return self._to_response(row)
