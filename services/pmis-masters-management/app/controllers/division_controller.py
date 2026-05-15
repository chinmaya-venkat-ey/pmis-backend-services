"""DivisionController — HTTP adapter for /masters/divisions/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.division import (
    DivisionCreateRequest,
    DivisionResponse,
    DivisionUpdateRequest,
)
from app.services.division_service import DivisionService


class DivisionController:
    def __init__(self, service: DivisionService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[DivisionResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [DivisionResponse.model_validate(r) for r in rows]

    def get_details(self, code: str) -> DivisionResponse:
        return DivisionResponse.model_validate(self.service.get_by_code(code))

    def create(self, payload: DivisionCreateRequest) -> DivisionResponse:
        return DivisionResponse.model_validate(self.service.create(payload))

    def update(self, code: str, payload: DivisionUpdateRequest) -> DivisionResponse:
        return DivisionResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> DivisionResponse:
        return DivisionResponse.model_validate(self.service.delete(code))

    def restore(self, code: str) -> DivisionResponse:
        return DivisionResponse.model_validate(self.service.restore(code))
