"""SlaActivityMappingRepository — DB access for sla_activity_mappings + joined SLA/formula info."""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.formula_library import FormulaLibrary
from app.models.sla_activity_mapping import SlaActivityMapping
from app.models.sla_definition import SlaDefinition


class SlaActivityMappingRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- writes

    def create(self, row: SlaActivityMapping) -> SlaActivityMapping:
        self.db.add(row)
        self.db.flush()
        self.db.refresh(row)
        return row

    def update(self, row: SlaActivityMapping, **kwargs) -> SlaActivityMapping:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    # ---------------------------------------------------------------- reads

    def get_by_id(self, mapping_id: str) -> Optional[SlaActivityMapping]:
        return self.db.execute(
            select(SlaActivityMapping).where(SlaActivityMapping.id == mapping_id)
        ).scalar_one_or_none()

    def find_overlap(
        self,
        activity_id: str,
        sla_id: str,
        effective_from,
    ) -> Optional[SlaActivityMapping]:
        """Same (activity, sla, effective_from) tuple already exists."""
        return self.db.execute(
            select(SlaActivityMapping).where(
                SlaActivityMapping.activity_id == activity_id,
                SlaActivityMapping.sla_id == sla_id,
                SlaActivityMapping.effective_from == effective_from,
            )
        ).scalar_one_or_none()

    def find_by_activity_and_sla_ref(
        self,
        activity_id: str,
        sla_ref: str,
        *,
        active_only: bool = True,
    ) -> Optional[Tuple[SlaActivityMapping, SlaDefinition, Optional[str]]]:
        """Look up a single (activity, SLA) mapping by the human-readable
        ``sla_ref`` instead of the internal ``mapping_id``.

        Used by the simple-evaluation endpoints so callers can say
        "PMU-SLA005" instead of remembering an opaque UUID. When more
        than one ACTIVE mapping exists for the same (activity, SLA) —
        which shouldn't happen given the unique constraint but is
        possible across effective_from dates — the most-recently
        effective row wins.
        """
        stmt = (
            select(SlaActivityMapping, SlaDefinition, FormulaLibrary.formula_type)
            .join(SlaDefinition, SlaActivityMapping.sla_id == SlaDefinition.id)
            .join(FormulaLibrary, SlaDefinition.formula_id == FormulaLibrary.id, isouter=True)
            .where(
                SlaActivityMapping.activity_id == activity_id,
                SlaDefinition.sla_ref == sla_ref,
                SlaDefinition.status != "DELETED",
            )
            .order_by(SlaActivityMapping.effective_from.desc())
            .limit(1)
        )
        if active_only:
            stmt = stmt.where(SlaActivityMapping.status == "ACTIVE")
        row = self.db.execute(stmt).first()
        return None if row is None else (row[0], row[1], row[2])

    def list_for_activity(
        self,
        activity_id: str,
        *,
        active_only: bool = True,
    ) -> List[Tuple[SlaActivityMapping, SlaDefinition, Optional[str]]]:
        """Return (mapping, sla_definition, formula_type) tuples for an activity."""
        stmt = (
            select(SlaActivityMapping, SlaDefinition, FormulaLibrary.formula_type)
            .join(SlaDefinition, SlaActivityMapping.sla_id == SlaDefinition.id)
            .join(FormulaLibrary, SlaDefinition.formula_id == FormulaLibrary.id, isouter=True)
            .where(SlaActivityMapping.activity_id == activity_id)
        )
        if active_only:
            stmt = stmt.where(SlaActivityMapping.status == "ACTIVE")
        stmt = stmt.order_by(SlaDefinition.sla_ref)
        return [(r[0], r[1], r[2]) for r in self.db.execute(stmt).all()]

    def load_with_sla(
        self, mapping_id: str
    ) -> Optional[Tuple[SlaActivityMapping, SlaDefinition, Optional[str]]]:
        stmt = (
            select(SlaActivityMapping, SlaDefinition, FormulaLibrary.formula_type)
            .join(SlaDefinition, SlaActivityMapping.sla_id == SlaDefinition.id)
            .join(FormulaLibrary, SlaDefinition.formula_id == FormulaLibrary.id, isouter=True)
            .where(SlaActivityMapping.id == mapping_id)
        )
        row = self.db.execute(stmt).first()
        if row is None:
            return None
        return (row[0], row[1], row[2])

    def list_by_sla(
        self, sla_id: str
    ) -> List[Tuple[SlaActivityMapping, SlaDefinition, Optional[str]]]:
        """All mappings attached to a given SLA template — for the FE's
        'Mapped Activities' panel on the SLA detail view."""
        stmt = (
            select(SlaActivityMapping, SlaDefinition, FormulaLibrary.formula_type)
            .join(SlaDefinition, SlaActivityMapping.sla_id == SlaDefinition.id)
            .join(FormulaLibrary, SlaDefinition.formula_id == FormulaLibrary.id, isouter=True)
            .where(SlaActivityMapping.sla_id == sla_id)
            .order_by(SlaActivityMapping.effective_from.desc())
        )
        return [(r[0], r[1], r[2]) for r in self.db.execute(stmt).all()]
