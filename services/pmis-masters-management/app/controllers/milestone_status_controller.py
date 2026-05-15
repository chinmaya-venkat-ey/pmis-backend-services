"""MilestoneStatusController — HTTP adapter for /masters/milestone-statuses/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.milestone_status import (
    MilestoneStatusCreateRequest,
    MilestoneStatusResponse,
    MilestoneStatusUpdateRequest,
)
from app.services.milestone_status_service import MilestoneStatusService


class MilestoneStatusController:
    def __init__(self, service: MilestoneStatusService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[MilestoneStatusResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [MilestoneStatusResponse.model_validate(r) for r in rows]

    def get_details(self, code: str) -> MilestoneStatusResponse:
        return MilestoneStatusResponse.model_validate(self.service.get_by_code(code))

    def create(self, payload: MilestoneStatusCreateRequest) -> MilestoneStatusResponse:
        return MilestoneStatusResponse.model_validate(self.service.create(payload))

    def update(
        self, code: str, payload: MilestoneStatusUpdateRequest
    ) -> MilestoneStatusResponse:
        return MilestoneStatusResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> MilestoneStatusResponse:
        return MilestoneStatusResponse.model_validate(self.service.delete(code))

    def restore(self, code: str) -> MilestoneStatusResponse:
        return MilestoneStatusResponse.model_validate(self.service.restore(code))
