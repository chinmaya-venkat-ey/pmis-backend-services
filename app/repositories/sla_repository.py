"""SlaRepository — DB access for all SLA-related tables."""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.formula_library import FormulaLibrary
from app.models.sla_asl_snapshot import SlaAslSnapshot
from app.models.sla_condition_band import SlaConditionBand
from app.models.sla_definition import SlaDefinition
from app.models.sla_dsl_version import SlaDslVersion
from app.models.sla_guard_condition import SlaGuardCondition
from app.models.sla_lookup_row import SlaLookupRow
from app.models.sla_metric import SlaMetric
from app.models.sla_parameter_value import SlaParameterValue
from app.models.sla_template import SlaTemplate


class SlaRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- formula

    def get_formula_by_type(self, formula_type: str) -> Optional[FormulaLibrary]:
        return self.db.execute(
            select(FormulaLibrary).where(
                FormulaLibrary.formula_type == formula_type,
                FormulaLibrary.is_active.is_(True),
            )
        ).scalar_one_or_none()

    # ---------------------------------------------------------------- sla_definitions

    def get_by_id(self, sla_id: str) -> Optional[SlaDefinition]:
        return self.db.execute(
            select(SlaDefinition).where(SlaDefinition.id == sla_id)
        ).scalar_one_or_none()

    def get_by_ref(self, contract_id: str, sla_ref: str) -> Optional[SlaDefinition]:
        return self.db.execute(
            select(SlaDefinition).where(
                SlaDefinition.contract_id == contract_id,
                SlaDefinition.sla_ref == sla_ref,
            )
        ).scalar_one_or_none()

    def list_for_contract(
        self,
        contract_id: str,
        *,
        status: Optional[str] = None,
        phase_id: Optional[str] = None,
    ) -> List[Tuple[SlaDefinition, str]]:
        """Return list of (SlaDefinition, formula_type) tuples."""
        stmt = (
            select(SlaDefinition, FormulaLibrary.formula_type)
            .join(FormulaLibrary, SlaDefinition.formula_id == FormulaLibrary.id)
            .where(SlaDefinition.contract_id == contract_id)
        )
        if status:
            stmt = stmt.where(SlaDefinition.status == status)
        if phase_id:
            stmt = stmt.where(SlaDefinition.phase_id == phase_id)
        stmt = stmt.order_by(SlaDefinition.sla_ref)
        return list(self.db.execute(stmt).all())

    def create(self, sla: SlaDefinition) -> SlaDefinition:
        self.db.add(sla)
        self.db.flush()
        self.db.refresh(sla)
        return sla

    def update_status(self, sla: SlaDefinition, status: str) -> SlaDefinition:
        sla.status = status
        self.db.flush()
        return sla

    # ---------------------------------------------------------------- sub-tables (bulk insert)

    def bulk_add(self, rows: list) -> None:
        for row in rows:
            self.db.add(row)
        self.db.flush()

    # ---------------------------------------------------------------- sub-table reads

    def get_metrics(self, sla_id: str) -> List[SlaMetric]:
        return list(
            self.db.execute(
                select(SlaMetric).where(SlaMetric.sla_id == sla_id)
            ).scalars().all()
        )

    def get_guards(self, sla_id: str) -> List[SlaGuardCondition]:
        return list(
            self.db.execute(
                select(SlaGuardCondition).where(SlaGuardCondition.sla_id == sla_id)
            ).scalars().all()
        )

    def get_parameters(self, sla_id: str) -> List[SlaParameterValue]:
        return list(
            self.db.execute(
                select(SlaParameterValue).where(SlaParameterValue.sla_id == sla_id)
            ).scalars().all()
        )

    def get_bands(self, sla_id: str) -> List[SlaConditionBand]:
        return list(
            self.db.execute(
                select(SlaConditionBand)
                .where(SlaConditionBand.sla_id == sla_id)
                .order_by(SlaConditionBand.metric_key, SlaConditionBand.sort_order)
            ).scalars().all()
        )

    def get_lookup_rows(self, sla_id: str) -> List[SlaLookupRow]:
        return list(
            self.db.execute(
                select(SlaLookupRow)
                .where(SlaLookupRow.sla_id == sla_id)
                .order_by(SlaLookupRow.sort_order)
            ).scalars().all()
        )

    # ---------------------------------------------------------------- DSL versions

    def get_current_dsl(self, sla_id: str, version: int) -> Optional[SlaDslVersion]:
        return self.db.execute(
            select(SlaDslVersion).where(
                SlaDslVersion.sla_id == sla_id,
                SlaDslVersion.version == version,
            )
        ).scalar_one_or_none()

    def get_current_asl(self, sla_id: str) -> Optional[SlaAslSnapshot]:
        return self.db.execute(
            select(SlaAslSnapshot).where(
                SlaAslSnapshot.sla_id == sla_id,
                SlaAslSnapshot.is_current.is_(True),
            )
        ).scalar_one_or_none()

    def retire_current_asl(self, sla_id: str) -> None:
        self.db.execute(
            update(SlaAslSnapshot)
            .where(SlaAslSnapshot.sla_id == sla_id, SlaAslSnapshot.is_current.is_(True))
            .values(is_current=False)
        )

    # ---------------------------------------------------------------- templates

    def get_template_by_ref(self, template_ref: str) -> Optional[SlaTemplate]:
        return self.db.execute(
            select(SlaTemplate).where(
                SlaTemplate.template_ref == template_ref,
                SlaTemplate.is_active.is_(True),
            )
        ).scalar_one_or_none()

    def list_templates(
        self, *, applicable_to: Optional[str] = None
    ) -> List[Tuple[SlaTemplate, str]]:
        """Return list of (SlaTemplate, formula_type) tuples."""
        stmt = (
            select(SlaTemplate, FormulaLibrary.formula_type)
            .join(FormulaLibrary, SlaTemplate.formula_id == FormulaLibrary.id)
            .where(SlaTemplate.is_active.is_(True))
        )
        if applicable_to:
            stmt = stmt.where(SlaTemplate.applicable_to.contains([applicable_to]))
        stmt = stmt.order_by(SlaTemplate.template_ref)
        return list(self.db.execute(stmt).all())
