"""RoleGrantsController — HTTP adapter for /user/role-grants/{role_name}/matrix."""
from __future__ import annotations

from app.schemas.role_grants import RoleGrantsMatrixResponse
from app.services.role_grants_service import RoleGrantsService


class RoleGrantsController:
    def __init__(self, service: RoleGrantsService):
        self.service = service

    def get_matrix(self, role_name: str) -> RoleGrantsMatrixResponse:
        return self.service.get_matrix_for(role_name)
