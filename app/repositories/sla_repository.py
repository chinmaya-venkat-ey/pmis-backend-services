"""SlaRepository — DB access for all SLA master tables."""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.formula_library import FormulaLibrary
from app.models.sla_condition_band import SlaConditionBand
from app.models.sla_definition import SlaDefinition
from app.models.sla_guard_condition import SlaGuardCondition
from app.models.sla_lookup_row import SlaLookupRow
from app.models.sla_metric import SlaMetric
from app.models.sla_parameter_value import SlaParameterValue


class SlaRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- definitions

    def get_by_ref(self, sla_ref: str) -> Optional[SlaDefinition]:
        return self.db.execute(
            select(SlaDefinition).where(SlaDefinition.sla_ref == sla_ref)
        ).scalar_one_or_none()

    def get_by_id(self, sla_id: str) -> Optional[SlaDefinition]:
        return self.db.execute(
            select(SlaDefinition).where(SlaDefinition.id == sla_id)
        ).scalar_one_or_none()

    def list_definitions_with_formula(
        self,
        *,
        contract_type: Optional[str] = None,
        formula_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Tuple[SlaDefinition, str]]:
        stmt = (
            select(SlaDefinition, FormulaLibrary.formula_type)
            .join(FormulaLibrary, SlaDefinition.formula_id == FormulaLibrary.id)
            .where(SlaDefinition.status != "DELETED")
        )
        if contract_type:
            stmt = stmt.where(SlaDefinition.contract_type == contract_type)
        if formula_type:
            stmt = stmt.where(FormulaLibrary.formula_type == formula_type)
        if status:
            stmt = stmt.where(SlaDefinition.status == status)
        stmt = stmt.order_by(SlaDefinition.sla_ref).offset(skip).limit(limit)
        rows = self.db.execute(stmt).all()
        return [(row[0], row[1]) for row in rows]

    def count_definitions(
        self,
        *,
        contract_type: Optional[str] = None,
        formula_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        from sqlalchemy import func
        stmt = (
            select(func.count())
            .select_from(SlaDefinition)
            .join(FormulaLibrary, SlaDefinition.formula_id == FormulaLibrary.id)
            .where(SlaDefinition.status != "DELETED")
        )
        if contract_type:
            stmt = stmt.where(SlaDefinition.contract_type == contract_type)
        if formula_type:
            stmt = stmt.where(FormulaLibrary.formula_type == formula_type)
        if status:
            stmt = stmt.where(SlaDefinition.status == status)
        return self.db.execute(stmt).scalar_one()

    def create_definition(self, row: SlaDefinition) -> SlaDefinition:
        self.db.add(row)
        self.db.flush()
        self.db.refresh(row)
        return row

    def update_dsl(
        self, defn: SlaDefinition, dsl_source: str, version: int
    ) -> SlaDefinition:
        defn.dsl_source = dsl_source
        defn.dsl_version = version
        self.db.flush()
        return defn

    # ---------------------------------------------------------------- metrics

    def bulk_add_metrics(self, rows: List[SlaMetric]) -> List[SlaMetric]:
        for r in rows:
            self.db.add(r)
        self.db.flush()
        return rows

    def list_metrics(self, sla_id: str) -> List[SlaMetric]:
        return list(
            self.db.execute(
                select(SlaMetric)
                .where(SlaMetric.sla_id == sla_id)
                .order_by(SlaMetric.metric_key)
            ).scalars().all()
        )

    # ---------------------------------------------------------------- parameters

    def bulk_add_parameters(self, rows: List[SlaParameterValue]) -> List[SlaParameterValue]:
        for r in rows:
            self.db.add(r)
        self.db.flush()
        return rows

    def list_parameters(self, sla_id: str) -> List[SlaParameterValue]:
        return list(
            self.db.execute(
                select(SlaParameterValue)
                .where(SlaParameterValue.sla_id == sla_id)
                .order_by(SlaParameterValue.param_key)
            ).scalars().all()
        )

    # ---------------------------------------------------------------- condition bands

    def bulk_add_bands(self, rows: List[SlaConditionBand]) -> List[SlaConditionBand]:
        for r in rows:
            self.db.add(r)
        self.db.flush()
        return rows

    def list_bands(self, sla_id: str) -> List[SlaConditionBand]:
        return list(
            self.db.execute(
                select(SlaConditionBand)
                .where(SlaConditionBand.sla_id == sla_id)
                .order_by(SlaConditionBand.sort_order, SlaConditionBand.band_label)
            ).scalars().all()
        )

    # ---------------------------------------------------------------- lookup rows

    def bulk_add_lookup_rows(self, rows: List[SlaLookupRow]) -> List[SlaLookupRow]:
        for r in rows:
            self.db.add(r)
        self.db.flush()
        return rows

    def list_lookup_rows(self, sla_id: str) -> List[SlaLookupRow]:
        return list(
            self.db.execute(
                select(SlaLookupRow)
                .where(SlaLookupRow.sla_id == sla_id)
                .order_by(SlaLookupRow.sort_order)
            ).scalars().all()
        )

    # ---------------------------------------------------------------- guard conditions

    def bulk_add_guards(self, rows: List[SlaGuardCondition]) -> List[SlaGuardCondition]:
        for r in rows:
            self.db.add(r)
        self.db.flush()
        return rows

    def list_guards(self, sla_id: str) -> List[SlaGuardCondition]:
        return list(
            self.db.execute(
                select(SlaGuardCondition)
                .where(SlaGuardCondition.sla_id == sla_id)
                .order_by(SlaGuardCondition.metric_key)
            ).scalars().all()
        )
