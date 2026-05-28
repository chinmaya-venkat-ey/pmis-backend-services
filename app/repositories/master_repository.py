"""MasterRepository — DB access for severity_master, contract_type_master, data_field_master, formula_library."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.contract_type_master import ContractTypeMaster
from app.models.data_field_master import DataFieldMaster
from app.models.formula_library import FormulaLibrary
from app.models.severity_master import SeverityMaster


class MasterRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- contract types

    def list_contract_types(self, *, active_only: bool = True) -> List[ContractTypeMaster]:
        stmt = select(ContractTypeMaster)
        if active_only:
            stmt = stmt.where(ContractTypeMaster.is_active.is_(True))
        return list(self.db.execute(stmt.order_by(ContractTypeMaster.code)).scalars().all())

    def get_contract_type(self, code: str) -> Optional[ContractTypeMaster]:
        return self.db.execute(
            select(ContractTypeMaster).where(ContractTypeMaster.code == code)
        ).scalar_one_or_none()

    def create_contract_type(self, row: ContractTypeMaster) -> ContractTypeMaster:
        self.db.add(row)
        self.db.flush()
        self.db.refresh(row)
        return row

    def update_contract_type(self, row: ContractTypeMaster, **kwargs) -> ContractTypeMaster:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    # ---------------------------------------------------------------- data fields

    def get_data_field(self, field_name: str) -> Optional[DataFieldMaster]:
        return self.db.execute(
            select(DataFieldMaster).where(
                DataFieldMaster.field_name == field_name,
                DataFieldMaster.is_active.is_(True),
            )
        ).scalar_one_or_none()

    def list_data_fields(
        self, *, contract_type: Optional[str] = None, active_only: bool = True
    ) -> List[DataFieldMaster]:
        stmt = select(DataFieldMaster)
        if active_only:
            stmt = stmt.where(DataFieldMaster.is_active.is_(True))
        if contract_type:
            # Include fields that apply to all types (NULL) OR contain this type
            stmt = stmt.where(
                or_(
                    DataFieldMaster.applicable_to.is_(None),
                    DataFieldMaster.applicable_to.contains([contract_type]),
                )
            )
        return list(self.db.execute(stmt.order_by(DataFieldMaster.display_name)).scalars().all())

    # ---------------------------------------------------------------- severity master

    def list_for_project(self, project_id: str) -> List[SeverityMaster]:
        return list(
            self.db.execute(
                select(SeverityMaster)
                .where(SeverityMaster.project_id == project_id)
                .order_by(SeverityMaster.level)
            ).scalars().all()
        )

    def get_level(self, project_id: str, level: int) -> Optional[SeverityMaster]:
        return self.db.execute(
            select(SeverityMaster).where(
                SeverityMaster.project_id == project_id,
                SeverityMaster.level == level,
            )
        ).scalar_one_or_none()

    def exists_for_project(self, project_id: str) -> bool:
        return (
            self.db.execute(
                select(SeverityMaster)
                .where(SeverityMaster.project_id == project_id)
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def bulk_create(self, rows: List[SeverityMaster]) -> List[SeverityMaster]:
        for r in rows:
            self.db.add(r)
        self.db.flush()
        return rows

    def update_level(self, row: SeverityMaster, **kwargs) -> SeverityMaster:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def delete_all_for_project(self, project_id: str) -> None:
        from sqlalchemy import delete
        self.db.execute(
            delete(SeverityMaster).where(SeverityMaster.project_id == project_id)
        )

    # ---------------------------------------------------------------- formula library

    def list_formula_library(self, *, active_only: bool = True) -> List[FormulaLibrary]:
        stmt = select(FormulaLibrary)
        if active_only:
            stmt = stmt.where(FormulaLibrary.is_active.is_(True))
        return list(self.db.execute(stmt.order_by(FormulaLibrary.formula_type)).scalars().all())

    def get_formula_by_type(self, formula_type: str) -> Optional[FormulaLibrary]:
        return self.db.execute(
            select(FormulaLibrary).where(FormulaLibrary.formula_type == formula_type)
        ).scalar_one_or_none()
