"""RoleController — HTTP adapter for /user/roles/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.role import (
    RoleCreateRequest,
    RolePermissionsReplaceRequest,
    RolePermissionsResponse,
    RoleResponse,
    RoleUpdateRequest,
)
from app.services.role_service import RoleService


class RoleController:
    def __init__(self, service: RoleService):
        self.service = service

    def list_(self) -> List[RoleResponse]:
        return [RoleResponse.model_validate(r) for r in self.service.list_()]

    def get_details(self, role_id: int) -> RoleResponse:
        return RoleResponse.model_validate(self.service.get_by_id(role_id))

    def create(self, payload: RoleCreateRequest) -> RoleResponse:
        return RoleResponse.model_validate(self.service.create(payload))

    def update(self, role_id: int, payload: RoleUpdateRequest) -> RoleResponse:
        return RoleResponse.model_validate(self.service.update(role_id, payload))

    def delete(self, role_id: int) -> RoleResponse:
        return RoleResponse.model_validate(self.service.delete(role_id))

    # ------------------------------------------------------------------ role-permission grants

    def list_role_permissions(self, role_id: int) -> RolePermissionsResponse:
        role, perms = self.service.list_role_permissions(role_id)
        return RolePermissionsResponse(
            role_id=role.id, role_name=role.name, permissions=perms,
        )

    def replace_role_permissions(self, role_id: int, payload: RolePermissionsReplaceRequest) -> RolePermissionsResponse:
        role, perms = self.service.replace_role_permissions(role_id, payload)
        return RolePermissionsResponse(
            role_id=role.id, role_name=role.name, permissions=perms,
        )

    def grant_permission(self, role_id: int, code: str) -> RolePermissionsResponse:
        role, perms = self.service.grant_permission_to_role(role_id, code)
        return RolePermissionsResponse(
            role_id=role.id, role_name=role.name, permissions=perms,
        )

    def revoke_permission(self, role_id: int, code: str) -> RolePermissionsResponse:
        role, perms = self.service.revoke_permission_from_role(role_id, code)
        return RolePermissionsResponse(
            role_id=role.id, role_name=role.name, permissions=perms,
        )
