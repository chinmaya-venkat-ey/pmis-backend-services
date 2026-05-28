"""MasterService — business logic for severity_master, contract_type_master, data_field_master."""
from __future__ import annotations

from typing import List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.contract_type_master import ContractTypeMaster
from app.models.severity_master import SeverityMaster
from app.repositories.master_repository import MasterRepository
from app.schemas.master import (
    ContractTypeCreateRequest,
    ContractTypeUpdateRequest,
    SeverityLevelUpdateRequest,
    SeverityMasterSetRequest,
)

# Standard MSAP scoring: level → (points, label)
_DEFAULT_SEVERITY_LEVELS = [
    (0, -2, "Exceptional / On Time"),
    (1,  2, "Minor Deviation"),
    (2,  4, "Moderate Deviation"),
    (3,  6, "Major Deviation"),
    (4,  8, "Critical / Severe Deviation"),
]


class MasterService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MasterRepository(db)

    # ---------------------------------------------------------------- contract types

    def list_contract_types(self):
        return self.repo.list_contract_types()

    def create_contract_type(self, payload: ContractTypeCreateRequest) -> ContractTypeMaster:
        existing = self.repo.get_contract_type(payload.code)
        if existing is not None:
            raise ConflictError(
                f"Contract type '{payload.code}' already exists",
                code="duplicate_contract_type",
            )
        row = ContractTypeMaster(
            code=payload.code,
            display_name=payload.display_name,
            description=payload.description,
            is_active=True,
        )
        return self.repo.create_contract_type(row)

    def update_contract_type(
        self, code: str, payload: ContractTypeUpdateRequest
    ) -> ContractTypeMaster:
        row = self.repo.get_contract_type(code)
        if row is None:
            raise NotFoundError(f"Contract type '{code}' not found")
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return row
        return self.repo.update_contract_type(row, **updates)

    def delete_contract_type(self, code: str) -> ContractTypeMaster:
        row = self.repo.get_contract_type(code)
        if row is None:
            raise NotFoundError(f"Contract type '{code}' not found")
        if not row.is_active:
            raise ConflictError(
                f"Contract type '{code}' is already inactive",
                code="already_inactive",
            )
        return self.repo.update_contract_type(row, is_active=False)

    # ---------------------------------------------------------------- data fields

    def list_data_fields(self, *, contract_type: Optional[str] = None):
        return self.repo.list_data_fields(contract_type=contract_type)

    # ---------------------------------------------------------------- formula library

    def list_formula_library(self):
        return self.repo.list_formula_library()

    # ---------------------------------------------------------------- severity master

    def list_severity_levels(self, project_id: str) -> List[SeverityMaster]:
        return self.repo.list_for_project(project_id)

    def seed_default_severity_levels(self, project_id: str) -> List[SeverityMaster]:
        """Idempotent — skips if levels already exist for this project."""
        if self.repo.exists_for_project(project_id):
            return self.repo.list_for_project(project_id)
        rows = [
            SeverityMaster(
                id=str(uuid4()),
                project_id=project_id,
                level=level,
                points=points,
                label=label,
            )
            for level, points, label in _DEFAULT_SEVERITY_LEVELS
        ]
        return self.repo.bulk_create(rows)

    def set_severity_levels(
        self, project_id: str, payload: SeverityMasterSetRequest
    ) -> List[SeverityMaster]:
        """Replace all severity levels for a project."""
        if len({item.level for item in payload.levels}) != len(payload.levels):
            raise ValidationError("Duplicate level values in request")
        self.repo.delete_all_for_project(project_id)
        rows = [
            SeverityMaster(
                id=str(uuid4()),
                project_id=project_id,
                level=item.level,
                points=item.points,
                label=item.label,
            )
            for item in sorted(payload.levels, key=lambda x: x.level)
        ]
        return self.repo.bulk_create(rows)

    def update_severity_level(
        self, project_id: str, level: int, payload: SeverityLevelUpdateRequest
    ) -> SeverityMaster:
        if level not in range(5):
            raise ValidationError("Severity level must be 0-4")
        row = self.repo.get_level(project_id, level)
        if row is None:
            raise NotFoundError(
                f"Severity level {level} not found for project '{project_id}'"
            )
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return row
        return self.repo.update_level(row, **updates)
