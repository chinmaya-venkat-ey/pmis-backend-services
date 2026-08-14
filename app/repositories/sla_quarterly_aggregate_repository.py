"""CRUD for contract.sla_quarterly_aggregate.

Writer: SlaComplianceService.rollup_quarterly (Phase B).
Reader: QuarterlySettlementService.close (Phase D) + the audit API.
Idempotency: the unique (mapping_id, fiscal_year, quarter) constraint on
the underlying table means upsert-by-primary-key is safe on re-run —
same day's second call replaces the row rather than duplicating it.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, List, Optional
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.sla_quarterly_aggregate import SlaQuarterlyAggregate
from app.utilities.quarter import QuarterKey


class SlaQuarterlyAggregateRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ reads

    def get(
        self, *, mapping_id: str, qk: QuarterKey,
    ) -> Optional[SlaQuarterlyAggregate]:
        return self.db.execute(
            select(SlaQuarterlyAggregate).where(and_(
                SlaQuarterlyAggregate.mapping_id == mapping_id,
                SlaQuarterlyAggregate.fiscal_year == qk.fiscal_year,
                SlaQuarterlyAggregate.quarter == qk.quarter,
            ))
        ).scalars().first()

    def list_for_project_quarter(
        self, *, project_id: str, qk: QuarterKey,
    ) -> List[SlaQuarterlyAggregate]:
        return list(self.db.execute(
            select(SlaQuarterlyAggregate).where(and_(
                SlaQuarterlyAggregate.project_id == project_id,
                SlaQuarterlyAggregate.fiscal_year == qk.fiscal_year,
                SlaQuarterlyAggregate.quarter == qk.quarter,
            )).order_by(SlaQuarterlyAggregate.sla_ref)
        ).scalars().all())

    # ------------------------------------------------------------------ delete

    def delete(self, *, mapping_id: str, qk: QuarterKey) -> int:
        """Remove the (mapping_id, fiscal_year, quarter) aggregate if present.

        Used to purge a STALE row when a mapping no longer belongs to a quarter
        it was previously (mis-)bucketed into — e.g. a breach recorded in Q3 for
        a Q2 activity, now that the rollup buckets by the activity's quarter.
        Returns the number of rows removed (0 or 1)."""
        existing = self.get(mapping_id=mapping_id, qk=qk)
        if existing is None:
            return 0
        self.db.delete(existing)
        self.db.commit()
        return 1

    # ------------------------------------------------------------------ upsert

    def upsert(
        self,
        *,
        mapping_id: str,
        sla_id: str,
        sla_ref: Optional[str],
        project_id: str,
        activity_id: str,
        qk: QuarterKey,
        accumulated_points: Optional[Decimal],
        derived_severity: Optional[int],
        ld_percent: Optional[Decimal],
        source_result_ids: Optional[Iterable[str]] = None,
        carried_forward: bool = False,
        notes: Optional[dict] = None,
    ) -> SlaQuarterlyAggregate:
        """Insert-or-update the (mapping_id, fiscal_year, quarter) row.

        Kept as get-then-mutate rather than PG-specific ON CONFLICT so the
        test suite (SQLite) exercises the same code path.
        """
        existing = self.get(mapping_id=mapping_id, qk=qk)
        srcs = list(source_result_ids) if source_result_ids is not None else None
        fields = dict(
            sla_id=sla_id,
            sla_ref=sla_ref,
            project_id=project_id,
            activity_id=activity_id,
            fiscal_year=qk.fiscal_year,
            quarter=qk.quarter,
            quarter_start=qk.quarter_start,
            quarter_end=qk.quarter_end,
            accumulated_points=accumulated_points,
            derived_severity=derived_severity,
            ld_percent=ld_percent,
            source_result_ids=srcs,
            carried_forward=carried_forward,
            notes=notes,
        )
        if existing is not None:
            for k, v in fields.items():
                setattr(existing, k, v)
            row = existing
        else:
            row = SlaQuarterlyAggregate(
                id=str(uuid4()), mapping_id=mapping_id, **fields,
            )
            self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
