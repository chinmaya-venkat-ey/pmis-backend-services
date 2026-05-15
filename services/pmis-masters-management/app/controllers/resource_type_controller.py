"""ResourceTypeController — HTTP adapter for /masters/resource-types/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.resource_type import (
    ResourceTypeCreateRequest,
    ResourceTypeResponse,
    ResourceTypeUpdateRequest,
)
from app.services.resource_type_service import ResourceTypeService


class ResourceTypeController:
    def __init__(self, service: ResourceTypeService):
        self.service = service

    def list_(self, *, include_inactive: bool = False) -> List[ResourceTypeResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [ResourceTypeResponse.model_validate(r) for r in rows]

    def get_details(self, rt_id: str) -> ResourceTypeResponse:
        return ResourceTypeResponse.model_validate(self.service.get_by_id(rt_id))

    def create(self, payload: ResourceTypeCreateRequest) -> ResourceTypeResponse:
        return ResourceTypeResponse.model_validate(self.service.create(payload))

    def update(
        self, rt_id: str, payload: ResourceTypeUpdateRequest
    ) -> ResourceTypeResponse:
        return ResourceTypeResponse.model_validate(self.service.update(rt_id, payload))

    def delete(self, rt_id: str) -> ResourceTypeResponse:
        return ResourceTypeResponse.model_validate(self.service.delete(rt_id))

    def restore(self, rt_id: str) -> ResourceTypeResponse:
        return ResourceTypeResponse.model_validate(self.service.restore(rt_id))
