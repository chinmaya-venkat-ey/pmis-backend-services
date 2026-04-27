"""User controller — orchestrates requests into service calls and maps
service results to HAL+JSON envelopes. Ported from the monolith.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.dependencies import get_current_user_id
from ....core.response import (
    format_collection_response,
    format_error_response,
    format_success_response,
    format_user_response,
)
from .schemas import (
    LoginRequest,
    UserCreateRequest,
    UserListQuery,
    UserPasswordUpdateRequest,
    UserUpdateRequest,
)
from .services import (
    authenticate_user,
    create_user,
    delete_user,
    get_user_by_id,
    list_users,
    logout_user,
    update_password,
    update_user,
)


class UserController:

    # ----- Create --------------------------------------------------------
    @staticmethod
    def create(request: Request, data: UserCreateRequest, db: Session) -> JSONResponse:
        result = create_user(
            db=db,
            login=data.login,
            email=data.email,
            password=data.password,
            first_name=data.firstName,
            last_name=data.lastName,
            admin=data.admin,
        )
        if result.is_success():
            return BaseController.created(format_user_response(result.data.to_dict()))
        error_payload = format_error_response(
            error_type=result.error_type, message=result.error, details=result.details,
        )
        status_code = 422 if result.error_type == "validation_error" else 409
        return BaseController.error(error_payload, status=status_code)

    # ----- Get -----------------------------------------------------------
    @staticmethod
    def get(request: Request, user_id: int, db: Session) -> JSONResponse:
        requesting_user_id = get_current_user_id(request)
        is_admin = getattr(request.state, "is_admin", False)
        result = get_user_by_id(
            db=db, user_id=user_id,
            requesting_user_id=requesting_user_id, is_admin=is_admin,
        )
        if result.is_success():
            return BaseController.ok(format_user_response(result.data.to_dict()))
        return BaseController.error(
            format_error_response(
                error_type=result.error_type,
                message=result.error, details=result.details,
            ),
            status=404,
        )

    # ----- Me ------------------------------------------------------------
    @staticmethod
    def get_me(request: Request, db: Session) -> JSONResponse:
        user_id = get_current_user_id(request)
        if not user_id:
            return BaseController.error(
                format_error_response(
                    error_type="authentication_error", message="Not authenticated",
                ),
                status=401,
            )
        result = get_user_by_id(
            db=db, user_id=user_id,
            requesting_user_id=user_id, is_admin=True,  # always view self
        )
        if result.is_success():
            return BaseController.ok(format_user_response(result.data.to_dict()))
        return BaseController.error(
            format_error_response(
                error_type=result.error_type,
                message=result.error, details=result.details,
            ),
            status=404,
        )

    # ----- List ----------------------------------------------------------
    @staticmethod
    def list(request: Request, query: UserListQuery, db: Session) -> JSONResponse:
        is_admin = getattr(request.state, "is_admin", False)
        result = list_users(
            db=db, page=query.offset, page_size=query.pageSize,
            status=query.status, is_admin=is_admin,
        )
        if result.is_success():
            p = result.data
            user_dicts = [u.to_dict() for u in p.items]
            return BaseController.ok(format_collection_response(
                items=user_dicts, total=p.total, page=p.page, page_size=p.page_size,
                collection_type="users",
            ))
        error_payload = format_error_response(
            error_type=result.error_type, message=result.error, details=result.details,
        )
        status_code = 422 if result.error_type == "validation_error" else 500
        return BaseController.error(error_payload, status=status_code)

    # ----- Update --------------------------------------------------------
    @staticmethod
    def update(
        request: Request, user_id: int, data: UserUpdateRequest, db: Session,
    ) -> JSONResponse:
        requesting_user_id = get_current_user_id(request)
        is_admin = getattr(request.state, "is_admin", False)
        result = update_user(
            db=db, user_id=user_id, email=data.email,
            first_name=data.firstName, last_name=data.lastName,
            admin=data.admin, status=data.status,
            requesting_user_id=requesting_user_id, is_admin=is_admin,
        )
        if result.is_success():
            return BaseController.ok(format_user_response(result.data.to_dict()))
        error_payload = format_error_response(
            error_type=result.error_type, message=result.error, details=result.details,
        )
        status_code = {
            "not_found": 404,
            "authorization_error": 403,
            "validation_error": 422,
        }.get(result.error_type, 500)
        return BaseController.error(error_payload, status=status_code)

    # ----- Update password ----------------------------------------------
    @staticmethod
    def update_password(
        request: Request, user_id: int,
        data: UserPasswordUpdateRequest, db: Session,
    ) -> JSONResponse:
        requesting_user_id = get_current_user_id(request)
        is_admin = getattr(request.state, "is_admin", False)
        result = update_password(
            db=db, user_id=user_id, new_password=data.password,
            requesting_user_id=requesting_user_id, is_admin=is_admin,
        )
        if result.is_success():
            return BaseController.ok(format_success_response(
                "Password updated successfully",
            ))
        error_payload = format_error_response(
            error_type=result.error_type, message=result.error, details=result.details,
        )
        status_code = {
            "not_found": 404,
            "authorization_error": 403,
            "validation_error": 422,
        }.get(result.error_type, 500)
        return BaseController.error(error_payload, status=status_code)

    # ----- Delete --------------------------------------------------------
    @staticmethod
    def delete(request: Request, user_id: int, db: Session) -> JSONResponse:
        result = delete_user(db=db, user_id=user_id)
        if result.is_success():
            return BaseController.ok(format_success_response(
                f"User {user_id} deleted successfully",
            ))
        error_payload = format_error_response(
            error_type=result.error_type, message=result.error, details=result.details,
        )
        status_code = 404 if result.error_type == "not_found" else 500
        return BaseController.error(error_payload, status=status_code)

    # ----- Login ---------------------------------------------------------
    @staticmethod
    def login(data: LoginRequest, db: Session) -> JSONResponse:
        result = authenticate_user(db=db, login=data.login, password=data.password)
        if result.is_success():
            td = result.data
            return BaseController.ok({
                "_type": "Login",
                "access_token": td["access_token"],
                "refresh_token": td.get("refresh_token"),
                "token_type": td["token_type"],
                "user": format_user_response(td["user"].to_dict()),
            })
        return BaseController.error(
            format_error_response(
                error_type=result.error_type,
                message=result.error, details=result.details,
            ),
            status=401,
        )

    # ----- Logout --------------------------------------------------------
    @staticmethod
    def logout(request: Request, db: Session) -> JSONResponse:
        user_id = get_current_user_id(request)
        if not user_id:
            return BaseController.error(
                format_error_response(
                    error_type="authentication_error", message="Not authenticated",
                ),
                status=401,
            )
        result = logout_user(
            db=db,
            user_id=user_id,
            token_jti=getattr(request.state, "token_jti", None),
            token_exp=getattr(request.state, "token_exp", None),
        )
        if result.is_success():
            return BaseController.ok(format_success_response(result.data["message"]))
        return BaseController.error(
            format_error_response(
                error_type=result.error_type, message=result.error,
            ),
            status=500,
        )

    # ----- Introspect ----------------------------------------------------
    @staticmethod
    def introspect(data, db: Session) -> JSONResponse:
        from .services.introspect import introspect_tokens

        result = introspect_tokens(
            db=db, access_token=data.access_token, refresh_token=data.refresh_token,
        )
        if result.is_success():
            payload = result.data
            if payload.get("active"):
                return BaseController.ok({
                    "_type": "Introspect",
                    "active": True,
                    "user": format_user_response(payload["user"].to_dict()),
                })
            return BaseController.ok({
                "_type": "Introspect",
                "access_token": payload.get("access_token"),
                "refresh_token": payload.get("refresh_token"),
                "token_type": payload.get("token_type"),
                "user": format_user_response(payload["user"].to_dict()),
            })
        return BaseController.error(
            format_error_response(
                error_type=result.error_type, message=result.error,
            ),
            status=401,
        )
