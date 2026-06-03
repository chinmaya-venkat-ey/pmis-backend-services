"""CostTypeController — HTTP adapter for /master/cost-types/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.cost_type import (
    CostTypeCreateRequest,
    CostTypeResponse,
    CostTypeUpdateRequest,
)
from app.services.cost_type_service import CostTypeService


class CostTypeController:
    def __init__(self, service: CostTypeService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[CostTypeResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [CostTypeResponse.model_validate(r) for r in rows]

    def get_details(self, code: str) -> CostTypeResponse:
        return CostTypeResponse.model_validate(self.service.get_by_code(code))

    def create(self, payload: CostTypeCreateRequest) -> CostTypeResponse:
        return CostTypeResponse.model_validate(self.service.create(payload))

    def update(self, code: str, payload: CostTypeUpdateRequest) -> CostTypeResponse:
        return CostTypeResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> CostTypeResponse:
        return CostTypeResponse.model_validate(self.service.delete(code))

    def restore(self, code: str) -> CostTypeResponse:
        return CostTypeResponse.model_validate(self.service.restore(code))
