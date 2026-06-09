"""MasterService — business logic for severity_master, project_ld_bands,
contract_type_master, data_field_master.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.contract_type_master import ContractTypeMaster
from app.models.data_field_master import DataFieldMaster
from app.models.project_ld_band import ProjectLdBand
from app.models.severity_master import SeverityMaster
from app.repositories.master_repository import MasterRepository
from app.schemas.master import (
    ContractTypeCreateRequest,
    ContractTypeUpdateRequest,
    LdBandSetRequest,
    LdBandUpdateRequest,
    SeverityLevelUpdateRequest,
    SeverityMasterSetRequest,
)

# Standard MSAP scoring: level → (points, label) — RFP Annexure-3E.
_DEFAULT_SEVERITY_LEVELS = [
    (0, -2, "Exceptional / On Time"),
    (1,  2, "Minor Deviation"),
    (2,  4, "Moderate Deviation"),
    (3,  6, "Major Deviation"),
    (4,  8, "Critical / Severe Deviation"),
]

# Standard MSAP scoring: points_threshold → (ld_percent, label).
# Mirrors DEFAULT_POINTS_TO_LD in point_accumulation.py so a freshly-seeded
# project produces the exact same output as a project that opts out of
# customisation.
_DEFAULT_LD_BANDS = [
    (Decimal("0"), Decimal("0"),   "On Target"),
    (Decimal("2"), Decimal("1"),   "Tier 1"),
    (Decimal("4"), Decimal("2"),   "Tier 2"),
    (Decimal("6"), Decimal("3"),   "Tier 3"),
    (Decimal("8"), Decimal("4"),   "Tier 4 / Cap"),
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

    def create_data_field(self, payload) -> DataFieldMaster:
        existing = self.repo.get_data_field(payload.field_name)
        if existing is not None:
            raise ConflictError(
                f"Data field '{payload.field_name}' already exists",
                code="duplicate_data_field",
            )
        row = DataFieldMaster(
            field_name=payload.field_name,
            display_name=payload.display_name,
            data_type=payload.data_type,
            unit=payload.unit,
            example_value=payload.example_value,
            applicable_to=payload.applicable_to,
            is_active=True,
        )
        return self.repo.create_data_field(row)

    def update_data_field(self, field_name: str, payload) -> DataFieldMaster:
        row = self.repo.get_data_field(field_name)
        if row is None:
            raise NotFoundError(f"Data field '{field_name}' not found")
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return row
        return self.repo.update_data_field(row, **updates)

    def delete_data_field(self, field_name: str) -> DataFieldMaster:
        row = self.repo.get_data_field(field_name)
        if row is None:
            raise NotFoundError(f"Data field '{field_name}' not found")
        if not row.is_active:
            raise ConflictError(
                f"Data field '{field_name}' is already inactive",
                code="already_inactive",
            )
        return self.repo.update_data_field(row, is_active=False)

    # ---------------------------------------------------------------- sla categories

    def list_sla_categories(self):
        return self.repo.list_sla_categories()

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
        """Upsert a severity level for a project.

        Levels are open-ended (L0, L1, ..., L4, L5, ... — no hard cap). PATCH is
        the only way to create a row for a level that doesn't exist yet, which
        keeps the API surface small and avoids drift between separate "create"
        and "update" endpoints.

        Behaviour:

          * Row exists — applies the patch as a partial update. Either ``points``
            or ``label`` (or both) may be supplied; omitted fields are left
            unchanged. An empty body is a no-op and returns the current row.
          * Row missing — creates a new row at this level. Both ``points`` and
            ``label`` are required for creation so we never persist a half-
            populated row; otherwise we surface a 400 to the caller.
        """
        row = self.repo.get_level(project_id, level)
        if row is None:
            if payload.points is None or payload.label is None:
                raise ValidationError(
                    f"Severity level {level} doesn't exist yet for project '{project_id}'. "
                    "Supply both 'points' and 'label' to create it.",
                    code="severity_level_create_requires_both_fields",
                )
            new_row = SeverityMaster(
                id=str(uuid4()),
                project_id=project_id,
                level=level,
                points=payload.points,
                label=payload.label,
            )
            created = self.repo.bulk_create([new_row])
            return created[0]
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return row
        return self.repo.update_level(row, **updates)

    # ---------------------------------------------------------------- project ld bands

    def list_ld_bands(self, project_id: str) -> List[ProjectLdBand]:
        return self.repo.list_ld_bands_for_project(project_id)

    def seed_default_ld_bands(self, project_id: str) -> List[ProjectLdBand]:
        """Idempotent — skips if any LD bands already exist for this project."""
        if self.repo.exists_ld_bands_for_project(project_id):
            return self.repo.list_ld_bands_for_project(project_id)
        rows = [
            ProjectLdBand(
                id=str(uuid4()),
                project_id=project_id,
                points_threshold=threshold,
                ld_percent=ld,
                label=label,
            )
            for threshold, ld, label in _DEFAULT_LD_BANDS
        ]
        return self.repo.bulk_create_ld_bands(rows)

    def set_ld_bands(
        self, project_id: str, payload: LdBandSetRequest
    ) -> List[ProjectLdBand]:
        """Replace all LD bands for a project."""
        thresholds = [item.points_threshold for item in payload.bands]
        if len(set(thresholds)) != len(thresholds):
            raise ValidationError("Duplicate points_threshold values in request")
        self.repo.delete_all_ld_bands_for_project(project_id)
        rows = [
            ProjectLdBand(
                id=str(uuid4()),
                project_id=project_id,
                points_threshold=item.points_threshold,
                ld_percent=item.ld_percent,
                label=item.label,
            )
            for item in sorted(payload.bands, key=lambda x: x.points_threshold)
        ]
        return self.repo.bulk_create_ld_bands(rows)

    def update_ld_band(
        self, project_id: str, band_id: str, payload: LdBandUpdateRequest
    ) -> ProjectLdBand:
        row = self.repo.get_ld_band(band_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError(
                f"LD band '{band_id}' not found for project '{project_id}'"
            )
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return row
        return self.repo.update_ld_band(row, **updates)

    # ---------------------------------------------------------------- combined seed

    def seed_master_defaults(self, project_id: str) -> Dict[str, int]:
        """Single-shot bootstrap for a fresh project.

        Seeds both severity_master and project_ld_bands with the RFP defaults
        when they're empty, leaves them alone when they're already populated.
        Returns a tiny summary the FE can show ("3 severity levels, 5 LD bands
        seeded" or "already configured").
        """
        sev_rows = self.seed_default_severity_levels(project_id)
        ld_rows = self.seed_default_ld_bands(project_id)
        return {
            "severity_levels": len(sev_rows),
            "ld_bands": len(ld_rows),
        }
