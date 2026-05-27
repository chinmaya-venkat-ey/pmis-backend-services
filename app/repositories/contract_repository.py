"""ContractRepository — DB access for contracts and contract_phases."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.contract import Contract
from app.models.contract_phase import ContractPhase


class ContractRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- contracts

    def get_by_id(self, contract_id: str) -> Optional[Contract]:
        return self.db.execute(
            select(Contract).where(Contract.id == contract_id)
        ).scalar_one_or_none()

    def get_by_ref(self, contract_ref: str) -> Optional[Contract]:
        return self.db.execute(
            select(Contract).where(Contract.contract_ref == contract_ref)
        ).scalar_one_or_none()

    def list_(
        self,
        *,
        offset: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        vendor_name: Optional[str] = None,
    ) -> Tuple[List[Contract], int]:
        stmt = select(Contract)
        count_stmt = select(func.count()).select_from(Contract)
        clauses = []

        if status:
            clauses.append(Contract.status == status)
        if vendor_name:
            clauses.append(Contract.vendor_name.ilike(f"%{vendor_name}%"))

        if clauses:
            from sqlalchemy import and_
            stmt = stmt.where(and_(*clauses))
            count_stmt = count_stmt.where(and_(*clauses))

        total = self.db.execute(count_stmt).scalar_one()
        rows = (
            self.db.execute(
                stmt.order_by(Contract.created_at.desc())
                .offset((offset - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        return list(rows), total

    def create(self, contract: Contract) -> Contract:
        self.db.add(contract)
        self.db.flush()
        self.db.refresh(contract)
        return contract

    def update(self, contract: Contract, **fields) -> Contract:
        for key, value in fields.items():
            setattr(contract, key, value)
        contract.updated_at = datetime.utcnow()
        self.db.flush()
        self.db.refresh(contract)
        return contract

    # ---------------------------------------------------------------- phases

    def get_phase_by_id(self, phase_id: str) -> Optional[ContractPhase]:
        return self.db.execute(
            select(ContractPhase).where(ContractPhase.id == phase_id)
        ).scalar_one_or_none()

    def list_phases(
        self, contract_id: str, *, active_only: bool = False
    ) -> List[ContractPhase]:
        stmt = select(ContractPhase).where(ContractPhase.contract_id == contract_id)
        if active_only:
            stmt = stmt.where(ContractPhase.is_active.is_(True))
        return list(
            self.db.execute(stmt.order_by(ContractPhase.start_date)).scalars().all()
        )

    def create_phase(self, phase: ContractPhase) -> ContractPhase:
        self.db.add(phase)
        self.db.flush()
        self.db.refresh(phase)
        return phase

    def update_phase(self, phase: ContractPhase, **fields) -> ContractPhase:
        for key, value in fields.items():
            setattr(phase, key, value)
        self.db.flush()
        self.db.refresh(phase)
        return phase
