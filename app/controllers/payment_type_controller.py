"""PaymentTypeController — HTTP adapter for /master/payment-types/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.payment_type import (
    PaymentTypeCreateRequest,
    PaymentTypeResponse,
    PaymentTypeUpdateRequest,
)
from app.services.payment_type_service import PaymentTypeService


class PaymentTypeController:
    def __init__(self, service: PaymentTypeService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[PaymentTypeResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [PaymentTypeResponse.model_validate(r) for r in rows]

    def get_details(self, code: str) -> PaymentTypeResponse:
        return PaymentTypeResponse.model_validate(self.service.get_by_code(code))

    def create(self, payload: PaymentTypeCreateRequest) -> PaymentTypeResponse:
        return PaymentTypeResponse.model_validate(self.service.create(payload))

    def update(self, code: str, payload: PaymentTypeUpdateRequest) -> PaymentTypeResponse:
        return PaymentTypeResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> PaymentTypeResponse:
        return PaymentTypeResponse.model_validate(self.service.delete(code))

    def restore(self, code: str) -> PaymentTypeResponse:
        return PaymentTypeResponse.model_validate(self.service.restore(code))
