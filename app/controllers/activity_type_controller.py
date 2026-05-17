"""ActivityTypeController — HTTP adapter for /masters/activity-types/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.activity_type import (
    ActivityTypeCreateRequest,
    ActivityTypeResponse,
    ActivityTypeUpdateRequest,
)
from app.services.activity_type_service import ActivityTypeService


class ActivityTypeController:
    def __init__(self, service: ActivityTypeService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[ActivityTypeResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [ActivityTypeResponse.model_validate(r) for r in rows]

    def get_details(self, code: str) -> ActivityTypeResponse:
        return ActivityTypeResponse.model_validate(self.service.get_by_code(code))

    def create(self, payload: ActivityTypeCreateRequest) -> ActivityTypeResponse:
        return ActivityTypeResponse.model_validate(self.service.create(payload))

    def update(
        self, code: str, payload: ActivityTypeUpdateRequest
    ) -> ActivityTypeResponse:
        return ActivityTypeResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> ActivityTypeResponse:
        return ActivityTypeResponse.model_validate(self.service.delete(code))

    def restore(self, code: str) -> ActivityTypeResponse:
        return ActivityTypeResponse.model_validate(self.service.restore(code))
