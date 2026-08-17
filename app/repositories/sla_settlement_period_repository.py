"""CRUD for contract.sla_settlement_period.

Writer: QuarterlySettlementService.close.
Reader: settlement audit API + payment page (Phase E).
Idempotency: unique (project_id, fiscal_year, quarter) constraint.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, List, Optional
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.sla_settlement_period import SlaSettlementPeriod
from app.utilities.quarter import QuarterKey


class SlaSettlementPeriodRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ reads

    def get(
        self, *, project_id: str, qk: QuarterKey,
    ) -> Optional[SlaSettlementPeriod]:
        return self.db.execute(
            select(SlaSettlementPeriod).where(and_(
                SlaSettlementPeriod.project_id == project_id,
                SlaSettlementPeriod.fiscal_year == qk.fiscal_year,
                SlaSettlementPeriod.quarter == qk.quarter,
            ))
        ).scalars().first()

    def list_for_project(self, project_id: str) -> List[SlaSettlementPeriod]:
        return list(self.db.execute(
            select(SlaSettlementPeriod)
            .where(SlaSettlementPeriod.project_id == project_id)
            .order_by(
                SlaSettlementPeriod.fiscal_year.desc(),
                SlaSettlementPeriod.quarter.desc(),
            )
        ).scalars().all())

    # ------------------------------------------------------------------ delete

    def delete(self, row: SlaSettlementPeriod) -> None:
        """Hard-delete a settlement period. Used by the refresh to prune orphan
        rows left behind by an anchor change (a stored ``(fiscal_year, quarter)``
        that no longer maps to any real quarter of the project's phase). Callers
        MUST exclude ``invoiced`` / ``overridden`` rows — those are authoritative
        finance commitments, never pruned."""
        if row.status == "invoiced":
            raise ValueError(
                f"Refusing to delete an invoiced settlement "
                f"({row.project_id} Y{row.fiscal_year}-Q{row.quarter})."
            )
        self.db.delete(row)
        self.db.commit()

    # ------------------------------------------------------------------ upsert

    def upsert(
        self,
        *,
        project_id: str,
        contract_type: Optional[str],
        qk: QuarterKey,
        sum_ld_percent: Optional[Decimal],
        capped_ld_percent: Optional[Decimal],
        f_amount: Optional[Decimal],
        qgr_amount: Optional[Decimal],
        npqp: Optional[Decimal],
        ld_amount: Optional[Decimal],
        pa_amount: Optional[Decimal],
        aqp_amount: Optional[Decimal],
        status: str,
        closed_by: Optional[str],
        override_reason: Optional[str],
        source_aggregate_ids: Optional[Iterable[str]] = None,
        consequence_flags: Optional[dict] = None,
    ) -> SlaSettlementPeriod:
        """Insert-or-update. Row is IMMUTABLE once ``status='invoiced'`` —
        caller (Phase E) must check before invoking this."""
        existing = self.get(project_id=project_id, qk=qk)
        if existing is not None and existing.status == "invoiced":
            # Guard against silent over-write; callers should have caught
            # this already but belt-and-braces.
            raise ValueError(
                f"Cannot mutate an invoiced settlement "
                f"({project_id} {qk.label()}) — issue a credit note instead.",
            )

        now = datetime.now(timezone.utc)
        src_ids = list(source_aggregate_ids) if source_aggregate_ids is not None else None
        fields = dict(
            contract_type=contract_type,
            fiscal_year=qk.fiscal_year,
            quarter=qk.quarter,
            quarter_start=qk.quarter_start,
            quarter_end=qk.quarter_end,
            sum_ld_percent=sum_ld_percent,
            capped_ld_percent=capped_ld_percent,
            f_amount=f_amount,
            qgr_amount=qgr_amount,
            npqp=npqp,
            ld_amount=ld_amount,
            pa_amount=pa_amount,
            aqp_amount=aqp_amount,
            status=status,
            closed_at=now if status in ("auto_closed", "overridden") else None,
            closed_by=closed_by,
            override_reason=override_reason,
            source_aggregate_ids=src_ids,
            consequence_flags=consequence_flags or {},
            updated_at=now,
        )
        if existing is not None:
            for k, v in fields.items():
                setattr(existing, k, v)
            row = existing
        else:
            row = SlaSettlementPeriod(
                id=str(uuid4()), project_id=project_id, **fields,
            )
            self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
