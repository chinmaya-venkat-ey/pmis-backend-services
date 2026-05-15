"""ActivityStatusController — HTTP adapter for /masters/activity-statuses/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.activity_status import (
    ActivityStatusCreateRequest,
    ActivityStatusResponse,
    ActivityStatusUpdateRequest,
)
from app.services.activity_status_service import ActivityStatusService


class ActivityStatusController:
    def __init__(self, service: ActivityStatusService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[ActivityStatusResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [ActivityStatusResponse.model_validate(r) for r in rows]

    def get_details(self, code: str) -> ActivityStatusResponse:
        return ActivityStatusResponse.model_validate(self.service.get_by_code(code))

    def create(self, payload: ActivityStatusCreateRequest) -> ActivityStatusResponse:
        return ActivityStatusResponse.model_validate(self.service.create(payload))

    def update(
        self, code: str, payload: ActivityStatusUpdateRequest
    ) -> ActivityStatusResponse:
        return ActivityStatusResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> ActivityStatusResponse:
        return ActivityStatusResponse.model_validate(self.service.delete(code))

    def restore(self, code: str) -> ActivityStatusResponse:
        return ActivityStatusResponse.model_validate(self.service.restore(code))
