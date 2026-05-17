"""PriorityController — HTTP adapter for /masters/priorities/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.priority import (
    PriorityCreateRequest,
    PriorityResponse,
    PriorityUpdateRequest,
)
from app.services.priority_service import PriorityService


class PriorityController:
    def __init__(self, service: PriorityService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[PriorityResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [PriorityResponse.model_validate(r) for r in rows]

    def get_details(self, code: str) -> PriorityResponse:
        return PriorityResponse.model_validate(self.service.get_by_code(code))

    def create(self, payload: PriorityCreateRequest) -> PriorityResponse:
        return PriorityResponse.model_validate(self.service.create(payload))

    def update(self, code: str, payload: PriorityUpdateRequest) -> PriorityResponse:
        return PriorityResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> PriorityResponse:
        return PriorityResponse.model_validate(self.service.delete(code))

    def restore(self, code: str) -> PriorityResponse:
        return PriorityResponse.model_validate(self.service.restore(code))
