"""ProjectLdConfigController — orchestrates service, shapes wire responses."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.project_ld_config import (
    ProjectLdConfigCreateRequest,
    ProjectLdConfigResponse,
    ProjectLdConfigUpdateRequest,
)
from app.services.project_ld_config_service import ProjectLdConfigService


class ProjectLdConfigController:
    def __init__(self, db: Session):
        self.service = ProjectLdConfigService(db)

    def get(self, project_id: str) -> ProjectLdConfigResponse:
        row = self.service.get_by_project_id(project_id)
        return ProjectLdConfigResponse.from_orm(row)

    def create(
        self,
        project_id: str,
        payload: ProjectLdConfigCreateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> ProjectLdConfigResponse:
        row = self.service.create(project_id, payload, caller_user_id=caller_user_id)
        return ProjectLdConfigResponse.from_orm(row)

    def update(
        self,
        project_id: str,
        payload: ProjectLdConfigUpdateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> ProjectLdConfigResponse:
        row = self.service.update(project_id, payload, caller_user_id=caller_user_id)
        return ProjectLdConfigResponse.from_orm(row)
