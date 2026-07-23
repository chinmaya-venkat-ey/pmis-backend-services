"""DesignationController — HTTP adapter for /masters/designations/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.designation import (
    DesignationCreateRequest,
    DesignationResponse,
    DesignationUpdateRequest,
)
from app.services.designation_service import DesignationService


class DesignationController:
    def __init__(self, service: DesignationService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[DesignationResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [DesignationResponse.model_validate(r) for r in rows]

    def get_details(self, designation_id: str) -> DesignationResponse:
        return DesignationResponse.model_validate(self.service.get_by_id(designation_id))

    def create(self, payload: DesignationCreateRequest) -> DesignationResponse:
        return DesignationResponse.model_validate(self.service.create(payload))

    def update(
        self, designation_id: str, payload: DesignationUpdateRequest
    ) -> DesignationResponse:
        return DesignationResponse.model_validate(
            self.service.update(designation_id, payload)
        )

    def delete(self, designation_id: str) -> DesignationResponse:
        return DesignationResponse.model_validate(self.service.delete(designation_id))

    def restore(self, designation_id: str) -> DesignationResponse:
        return DesignationResponse.model_validate(self.service.restore(designation_id))
