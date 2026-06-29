"""CarryForwardMethodController — HTTP adapter for
/master/carry-forward-methods/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.carry_forward_method import (
    CarryForwardMethodCreateRequest,
    CarryForwardMethodResponse,
    CarryForwardMethodUpdateRequest,
)
from app.services.carry_forward_method_service import CarryForwardMethodService


class CarryForwardMethodController:
    def __init__(self, service: CarryForwardMethodService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[CarryForwardMethodResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [CarryForwardMethodResponse.model_validate(r) for r in rows]

    def get_details(self, code: str) -> CarryForwardMethodResponse:
        return CarryForwardMethodResponse.model_validate(self.service.get_by_code(code))

    def create(self, payload: CarryForwardMethodCreateRequest) -> CarryForwardMethodResponse:
        return CarryForwardMethodResponse.model_validate(self.service.create(payload))

    def update(self, code: str, payload: CarryForwardMethodUpdateRequest) -> CarryForwardMethodResponse:
        return CarryForwardMethodResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> CarryForwardMethodResponse:
        return CarryForwardMethodResponse.model_validate(self.service.delete(code))

    def restore(self, code: str) -> CarryForwardMethodResponse:
        return CarryForwardMethodResponse.model_validate(self.service.restore(code))
