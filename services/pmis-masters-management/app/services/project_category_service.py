"""Business logic for the project_categories catalog."""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import (
    CatalogEntryConflictError,
    CatalogEntryNotFoundError,
)
from app.models.project_category import ProjectCategory
from app.repositories.project_category_repository import ProjectCategoryRepository
from app.schemas.project_category import (
    ProjectCategoryCreateRequest,
    ProjectCategoryUpdateRequest,
)


class ProjectCategoryService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectCategoryRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[ProjectCategory]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_code(self, code: str) -> ProjectCategory:
        row = self.repo.get_by_code(code)
        if row is None:
            raise CatalogEntryNotFoundError(f"ProjectCategory code {code!r} not found")
        return row

    def create(self, payload: ProjectCategoryCreateRequest) -> ProjectCategory:
        if self.repo.get_by_code(payload.code) is not None:
            raise CatalogEntryConflictError(
                f"ProjectCategory code {payload.code!r} already exists",
                details={"code": payload.code},
            )
        row = self.repo.create(
            code=payload.code,
            label=payload.label,
            is_builtin=False,
            requires_other=payload.requires_other,
            active=payload.active,
            description=payload.description,
        )
        self.db.commit()
        return row

    def update(self, code: str, payload: ProjectCategoryUpdateRequest) -> ProjectCategory:
        row = self.get_by_code(code)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, code: str) -> ProjectCategory:
        row = self.get_by_code(code)
        # is_builtin is informational only — all categories are deletable.
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, code: str) -> ProjectCategory:
        row = self.get_by_code(code)
        self.repo.reactivate(row)
        self.db.commit()
        return row
