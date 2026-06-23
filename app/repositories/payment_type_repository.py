"""Data access for the payment-types catalog. Delete via active=False."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payment_type import PaymentType


class PaymentTypeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, payment_type_id: str) -> Optional[PaymentType]:
        return self.db.get(PaymentType, payment_type_id)

    def get_by_code(self, code: str) -> Optional[PaymentType]:
        stmt = select(PaymentType).where(PaymentType.code == code.lower())
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[PaymentType]:
        stmt = select(PaymentType)
        if not include_inactive:
            stmt = stmt.where(PaymentType.active.is_(True))
        stmt = stmt.order_by(PaymentType.position.asc(), PaymentType.code.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> PaymentType:
        row = PaymentType(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: PaymentType, **kwargs) -> PaymentType:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: PaymentType) -> PaymentType:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: PaymentType) -> PaymentType:
        row.active = True
        self.db.flush()
        return row
