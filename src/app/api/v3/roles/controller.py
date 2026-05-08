"""
Role controller - orchestrates requests and responses.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from .schemas import (
    RoleCreateRequest,
    RoleUpdateRequest,
    RoleListQuery
)
from .services.create import create_role
from .services.get import get_role_by_id
from .services.list import list_roles
from .services.update import update_role
from .services.delete import delete_role
from ....core.response import (
    format_role_response,
    format_collection_response,
    format_error_response,
)
from ....core.base_controller import BaseController


class RoleController:
    """Controller for role operations."""

    @staticmethod
    def create(
        request: Request,
        data: RoleCreateRequest,
        db: Session
    ) -> JSONResponse:
        """
        Create a new role.

        Args:
            request: FastAPI request
            data: Role creation data
            db: Database session

        Returns:
            JSONResponse
        """
        result = create_role(
            db=db,
            name=data.name,
            permissions=data.permissions,
            builtin=False,  # custom roles are never builtin
            description=data.description,
        )

        if result.is_success():
            payload = format_role_response(result.data.to_dict())
            resp = BaseController.created(payload)
            return resp
        else:
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )
            status_code = 422 if result.error_type == "validation_error" else 409
            resp = BaseController.error(error_payload, status=status_code)
            return resp

    @staticmethod
    def get(
        request: Request,
        role_id: int,
        db: Session
    ) -> JSONResponse:
        """
        Get role by ID.

        Args:
            request: FastAPI request
            role_id: Role ID
            db: Database session

        Returns:
            JSONResponse
        """
        result = get_role_by_id(db=db, role_id=role_id)

        if result.is_success():
            payload = format_role_response(result.data.to_dict())
            resp = BaseController.ok(payload)
            return resp
        else:
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )
            status_code = 404 if result.error_type == "not_found" else 400
            resp = BaseController.error(error_payload, status=status_code)
            return resp

    @staticmethod
    def list(
        request: Request,
        query: RoleListQuery,
        db: Session
    ) -> JSONResponse:
        """
        List roles with pagination.

        Args:
            request: FastAPI request
            query: Query parameters
            db: Database session

        Returns:
            JSONResponse
        """
        result = list_roles(
            db=db,
            offset=query.offset,
            limit=query.pageSize
        )

        if result.is_success():
            roles, total = result.data
            # Calculate page number from offset
            page = (query.offset // query.pageSize) + 1 if query.offset > 0 else 1
            payload = format_collection_response(
                items=[role.to_dict() for role in roles],
                total=total,
                page=page,
                page_size=query.pageSize,
                collection_type="roles"
            )
            resp = BaseController.ok(payload)
            return resp
        else:
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )
            status_code = 422 if result.error_type == "validation_error" else 400
            resp = BaseController.error(error_payload, status=status_code)
            return resp

    @staticmethod
    def update(
        request: Request,
        role_id: int,
        data: RoleUpdateRequest,
        db: Session
    ) -> JSONResponse:
        """
        Update role details.

        Args:
            request: FastAPI request
            role_id: Role ID
            data: Update data
            db: Database session

        Returns:
            JSONResponse
        """
        result = update_role(
            db=db,
            role_id=role_id,
            name=data.name,
            permissions=data.permissions,
            description=data.description,
        )

        if result.is_success():
            payload = format_role_response(result.data.to_dict())
            resp = BaseController.ok(payload)
            return resp
        else:
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )
            if result.error_type == "not_found":
                status_code = 404
            elif result.error_type == "validation_error":
                status_code = 422
            elif result.error_type == "forbidden":
                status_code = 403
            else:
                status_code = 409
            resp = BaseController.error(error_payload, status=status_code)
            return resp

    @staticmethod
    def delete(
        request: Request,
        role_id: int,
        db: Session
    ) -> JSONResponse:
        """
        Delete role.

        Args:
            request: FastAPI request
            role_id: Role ID
            db: Database session

        Returns:
            JSONResponse
        """
        result = delete_role(db=db, role_id=role_id)

        if result.is_success():
            resp = BaseController.no_content()
            return resp
        else:
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )
            if result.error_type == "not_found":
                status_code = 404
            elif result.error_type == "forbidden":
                status_code = 403
            else:
                status_code = 400
            resp = BaseController.error(error_payload, status=status_code)
            return resp
