"""User controller — orchestrates requests into service calls and maps
service results to HAL+JSON envelopes.
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
    restore_user,
    update_password,
    update_user,
)


class UserController:
    """Controller for user operations."""

    # ----- Create --------------------------------------------------------
    @staticmethod
    def create(
        request: Request, data: UserCreateRequest, db: Session,
    ) -> JSONResponse:
        result = create_user(
            db=db,
            login=data.login,
            email=data.email,
            password=data.password,
            first_name=data.firstName,
            last_name=data.lastName,
            admin=data.admin,
            vendor_id=data.vendorId,
            division=data.division,
            division_other=data.divisionOther,
            project_ids=data.projectIds,
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
            include_deleted=getattr(query, "includeDeleted", False),
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
        status_code = (
            422 if result.error_type == "validation_error"
            else 403 if result.error_type == "authorization_error"
            else 500
        )
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
            vendor_id=data.vendorId,
            division=data.division,
            division_other=data.divisionOther,
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
            "already_exists": 409,
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

    # ----- Delete (soft) -------------------------------------------------
    @staticmethod
    def delete(request: Request, user_id: int, db: Session) -> JSONResponse:
        actor_id = get_current_user_id(request)
        result = delete_user(db=db, user_id=user_id, actor_id=actor_id)
        if result.is_success():
            return BaseController.ok(format_success_response(
                f"User {user_id} deleted successfully",
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

    # ----- Restore -------------------------------------------------------
    @staticmethod
    def restore(request: Request, user_id: int, db: Session) -> JSONResponse:
        """Restore a soft-deleted user. Idempotent on already-active users."""
        requesting_user_id = get_current_user_id(request)
        is_admin = getattr(request.state, "is_admin", False)

        result = restore_user(
            db=db,
            user_id=user_id,
            requesting_user_id=requesting_user_id,
            is_admin=is_admin,
        )

        if result.is_success():
            return BaseController.ok(format_user_response(result.data.to_dict()))
        error_payload = format_error_response(
            error_type=result.error_type,
            message=result.error,
            details=result.details,
        )
        status_code = {
            "not_found": 404,
            "authorization_error": 403,
        }.get(result.error_type, 500)
        return BaseController.error(error_payload, status=status_code)

    # ----- Login ---------------------------------------------------------
    @staticmethod
    def login(data: LoginRequest, db: Session) -> JSONResponse:
        result = authenticate_user(db=db, login=data.login, password=data.password)
        if result.is_success():
            td = result.data
            # Decode the freshly-minted tokens to surface their expiry /
            # issued-at timestamps to the FE. Lets the client schedule a
            # preemptive refresh without having to decode the JWT itself.
            from .services.refresh import _exp_metadata
            access_meta = _exp_metadata(td["access_token"])
            refresh_meta = (
                _exp_metadata(td["refresh_token"])
                if td.get("refresh_token") else {}
            )
            return BaseController.ok({
                "_type": "Login",
                "access_token": td["access_token"],
                "refresh_token": td.get("refresh_token"),
                "token_type": td["token_type"],
                "accessTokenExpiresAt": access_meta.get("expiresAt"),
                "accessTokenIssuedAt": access_meta.get("issuedAt"),
                "refreshTokenExpiresAt": refresh_meta.get("expiresAt"),
                "refreshTokenIssuedAt": refresh_meta.get("issuedAt"),
                "expiresInSeconds": (
                    int(access_meta["exp"] - access_meta["iat"])
                    if access_meta.get("exp") and access_meta.get("iat") else None
                ),
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

    # ----- Introspect (RFC 7662 read-only) -------------------------------
    @staticmethod
    def introspect(data, db: Session) -> JSONResponse:
        from .services.introspect import introspect_tokens

        result = introspect_tokens(
            db=db, access_token=data.access_token, refresh_token=data.refresh_token,
        )

        if not result.is_success():
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
            )
            status = 422 if result.error_type == "validation_error" else 401
            return BaseController.error(error_payload, status=status)

        payload = result.data
        # Tag the envelope so the FE can disambiguate from other responses.
        if isinstance(payload, dict):
            payload = {**payload, "_type": "Introspect"}
        return BaseController.ok(payload)

    # ----- Refresh (rotates access + refresh) ----------------------------
    @staticmethod
    def refresh(data, db: Session) -> JSONResponse:
        """Public refresh endpoint. Validates a refresh token and returns
        a freshly-rotated access + refresh pair plus expiry metadata.
        """
        from .services.refresh import refresh_tokens

        result = refresh_tokens(db=db, refresh_token=data.refresh_token)

        if not result.is_success():
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
            )
            status = 422 if result.error_type == "validation_error" else 401
            return BaseController.error(error_payload, status=status)

        payload = result.data
        return BaseController.ok({
            "_type": "Refresh",
            "access_token": payload["access_token"],
            "refresh_token": payload["refresh_token"],
            "token_type": payload["token_type"],
            "accessTokenExpiresAt": payload.get("accessTokenExpiresAt"),
            "accessTokenIssuedAt": payload.get("accessTokenIssuedAt"),
            "refreshTokenExpiresAt": payload.get("refreshTokenExpiresAt"),
            "refreshTokenIssuedAt": payload.get("refreshTokenIssuedAt"),
            "expiresInSeconds": payload.get("expiresInSeconds"),
            "user": format_user_response(payload["user"].to_dict()),
        })
