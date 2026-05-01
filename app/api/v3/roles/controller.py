"""Role controller — orchestrates requests and responses."""
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.response import (
    format_collection_response,
    format_error_response,
    format_role_response,
)
from .schemas import RoleCreateRequest, RoleListQuery, RoleUpdateRequest
from .services.create import create_role
from .services.delete import delete_role
from .services.get import get_role_by_id
from .services.list import list_roles
from .services.update import update_role


class RoleController:
    """Controller for role operations."""

    @staticmethod
    def create(
        request: Request, data: RoleCreateRequest, db: Session,
    ) -> JSONResponse:
        result = create_role(
            db=db, name=data.name, permissions=data.permissions, builtin=data.builtin,
        )
        if result.is_success():
            return BaseController.created(format_role_response(result.data.to_dict()))
        error_payload = format_error_response(
            error_type=result.error_type, message=result.error, details=result.details,
        )
        status_code = 422 if result.error_type == "validation_error" else 409
        return BaseController.error(error_payload, status=status_code)

    @staticmethod
    def get(request: Request, role_id: int, db: Session) -> JSONResponse:
        result = get_role_by_id(db=db, role_id=role_id)
        if result.is_success():
            return BaseController.ok(format_role_response(result.data.to_dict()))
        error_payload = format_error_response(
            error_type=result.error_type, message=result.error, details=result.details,
        )
        status_code = 404 if result.error_type == "not_found" else 400
        return BaseController.error(error_payload, status=status_code)

    @staticmethod
    def list(request: Request, query: RoleListQuery, db: Session) -> JSONResponse:
        result = list_roles(db=db, offset=query.offset, limit=query.pageSize)
        if result.is_success():
            roles, total = result.data
            page = (query.offset // query.pageSize) + 1 if query.offset > 0 else 1
            return BaseController.ok(format_collection_response(
                items=[role.to_dict() for role in roles],
                total=total,
                page=page,
                page_size=query.pageSize,
                collection_type="roles",
            ))
        error_payload = format_error_response(
            error_type=result.error_type, message=result.error, details=result.details,
        )
        status_code = 422 if result.error_type == "validation_error" else 400
        return BaseController.error(error_payload, status=status_code)

    @staticmethod
    def update(
        request: Request, role_id: int, data: RoleUpdateRequest, db: Session,
    ) -> JSONResponse:
        result = update_role(
            db=db, role_id=role_id, name=data.name, permissions=data.permissions,
        )
        if result.is_success():
            return BaseController.ok(format_role_response(result.data.to_dict()))
        error_payload = format_error_response(
            error_type=result.error_type, message=result.error, details=result.details,
        )
        status_code = {
            "not_found": 404,
            "validation_error": 422,
            "forbidden": 403,
            "already_exists": 409,
        }.get(result.error_type, 409)
        return BaseController.error(error_payload, status=status_code)

    @staticmethod
    def delete(request: Request, role_id: int, db: Session) -> JSONResponse:
        result = delete_role(db=db, role_id=role_id)
        if result.is_success():
            return BaseController.no_content()
        error_payload = format_error_response(
            error_type=result.error_type, message=result.error, details=result.details,
        )
        status_code = {
            "not_found": 404,
            "forbidden": 403,
        }.get(result.error_type, 400)
        return BaseController.error(error_payload, status=status_code)
