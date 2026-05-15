"""ProjectCategoryController — HTTP adapter for /masters/project-categories/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.project_category import (
    ProjectCategoryCreateRequest,
    ProjectCategoryResponse,
    ProjectCategoryUpdateRequest,
)
from app.services.project_category_service import ProjectCategoryService


class ProjectCategoryController:
    def __init__(self, service: ProjectCategoryService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[ProjectCategoryResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [ProjectCategoryResponse.model_validate(r) for r in rows]

    def get_details(self, code: str) -> ProjectCategoryResponse:
        return ProjectCategoryResponse.model_validate(self.service.get_by_code(code))

    def create(
        self, payload: ProjectCategoryCreateRequest
    ) -> ProjectCategoryResponse:
        return ProjectCategoryResponse.model_validate(self.service.create(payload))

    def update(
        self, code: str, payload: ProjectCategoryUpdateRequest
    ) -> ProjectCategoryResponse:
        return ProjectCategoryResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> ProjectCategoryResponse:
        return ProjectCategoryResponse.model_validate(self.service.delete(code))

    def restore(self, code: str) -> ProjectCategoryResponse:
        return ProjectCategoryResponse.model_validate(self.service.restore(code))
