"""PermissionController — HTTP adapter for /user/permissions/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.permission import (
    PermissionCreateRequest,
    PermissionResponse,
    PermissionUpdateRequest,
    PermissionsByModuleResponse,
)
from app.services.permission_service import PermissionService


class PermissionController:
    def __init__(self, service: PermissionService):
        self.service = service

    def list_(self) -> List[PermissionResponse]:
        return [PermissionResponse.model_validate(p) for p in self.service.list_()]

    def by_module(self) -> PermissionsByModuleResponse:
        return self.service.by_module()

    def get_details(self, code: str) -> PermissionResponse:
        return PermissionResponse.model_validate(self.service.get_by_code(code))

    def create(self, payload: PermissionCreateRequest) -> PermissionResponse:
        return PermissionResponse.model_validate(self.service.create(payload))

    def update(self, code: str, payload: PermissionUpdateRequest) -> PermissionResponse:
        return PermissionResponse.model_validate(self.service.update(code, payload))

    def delete(self, code: str) -> PermissionResponse:
        return PermissionResponse.model_validate(self.service.delete(code))
