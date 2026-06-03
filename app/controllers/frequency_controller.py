"""FrequencyController — HTTP adapter for /master/frequencies/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.frequency import (
    FrequencyCreateRequest,
    FrequencyResponse,
    FrequencyUpdateRequest,
)
from app.services.frequency_service import FrequencyService


class FrequencyController:
    def __init__(self, service: FrequencyService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[FrequencyResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [FrequencyResponse.model_validate(r) for r in rows]

    def get_details(self, code: str) -> FrequencyResponse:
        return FrequencyResponse.model_validate(self.service.get_by_code(code))

    def create(self, payload: FrequencyCreateRequest) -> FrequencyResponse:
        return FrequencyResponse.model_validate(self.service.create(payload))

    def update(self, code: str, payload: FrequencyUpdateRequest) -> FrequencyResponse:
        return FrequencyResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> FrequencyResponse:
        return FrequencyResponse.model_validate(self.service.delete(code))

    def restore(self, code: str) -> FrequencyResponse:
        return FrequencyResponse.model_validate(self.service.restore(code))
