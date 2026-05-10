"""
User controller - orchestrates requests and responses.
"""
from typing import Any, Dict, List, Optional
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from .schemas import (
    UserCreateRequest,
    UserUpdateRequest,
    UserPasswordUpdateRequest,
    LoginRequest,
    UserListQuery
)
from .services import (
    create_user,
    get_user_by_id,
    list_users,
    update_user,
    update_password,
    delete_user,
    restore_user,
    authenticate_user,
    logout_user,
)
from ....core.response import (
    format_user_response,
    format_collection_response,
    format_error_response,
    format_success_response
)
from ....core.base_controller import BaseController
from ....core.dependencies import get_current_user_id
from ....infrastructure.db.repositories.user_repository import UserRepository


def _resolve_user_id(db: Session, user_id):
    """Resolve either a UUID or a ``US-...`` code to the canonical UUID.
    Returns ``None`` if the input doesn't map to a live user (caller
    surfaces 404).

    Doc 26: ``users.id`` is now a UUID string (was integer pre-doc-26),
    so this is identical to vendor's ``resolve_id`` — UUID-or-code, no
    int coercion. Every controller action that takes a path-param user
    id funnels through here.
    """
    return UserRepository(db).resolve_id(user_id)


class UserController:
    """Controller for user operations."""

    @staticmethod
    def create(
        request: Request,
        data: UserCreateRequest,
        db: Session
    ) -> JSONResponse:
        """
        Create a new user.

        Args:
            request: FastAPI request
            data: User creation data
            db: Database session

        Returns:
            JSONResponse
        """
        # Doc 44: pass caller_id so the create service can run the
        # caller-vs-target gate when orgRole is requested. Combine
        # the two FE arrays (projectAssignments + assignments) into
        # a single list of dicts before handing off to the service.
        caller_id = get_current_user_id(request)
        merged_assignments: List[Dict[str, Any]] = []
        for entry in (data.projectAssignments or []):
            merged_assignments.append({
                "projectId": entry.projectId, "role": entry.role,
            })
        for entry in (data.assignments or []):
            merged_assignments.append({
                "projectId": entry.projectId, "role": entry.role,
            })

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
            phone_number=data.phoneNumber,
            org_role=data.orgRole,
            project_assignments=merged_assignments or None,
            caller_id=caller_id,
        )

        if result.is_success():
            payload = format_user_response(result.data.to_dict(), db=db)
            resp = BaseController.created(payload)
            return resp
        else:
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )
            # Status mapping: validation → 422, authorization → 403,
            # not_found → 404, default (already_exists / internal) → 409.
            if result.error_type == "validation_error":
                status_code = 422
            elif result.error_type == "authorization_error":
                status_code = 403
            elif result.error_type == "not_found":
                status_code = 404
            else:
                status_code = 409
            resp = BaseController.error(error_payload, status=status_code)
            return resp

    @staticmethod
    def get(
        request: Request,
        user_id,
        db: Session
    ) -> JSONResponse:
        """
        Get user by ID.

        Args:
            request: FastAPI request
            user_id: User ID — accepts integer ``id`` or ``US-...`` code
                (doc 25). The dispatch happens here so the service layer
                keeps its existing integer-only signature.
            db: Database session

        Returns:
            JSONResponse
        """
        requesting_user_id = get_current_user_id(request)
        is_admin = getattr(request.state, "is_admin", False)

        canonical_id = _resolve_user_id(db, user_id)
        if canonical_id is None:
            return BaseController.error(
                format_error_response(
                    error_type="not_found",
                    message=f"User with ID {user_id} not found",
                ),
                status=404,
            )

        # Doc 44 round 9 — F1 read-side hierarchy guard. Only
        # super_admin can read another super_admin's profile (PATCH /
        # password / DELETE were already blocked by F1 in round 7;
        # GET was the remaining gap). Self-fetch always allowed.
        if (
            requesting_user_id is not None
            and requesting_user_id != canonical_id
        ):
            from ....infrastructure.db.repositories.rbac_repository import (
                RbacRepository,
            )
            repo_rbac = RbacRepository(db)
            target_is_super_admin = repo_rbac.user_has_super_admin_role(
                canonical_id,
            )
            caller_is_super_admin = repo_rbac.user_has_super_admin_role(
                requesting_user_id,
            )
            if target_is_super_admin and not caller_is_super_admin:
                return BaseController.error(
                    format_error_response(
                        error_type="forbidden",
                        message="Only super_admin can view a super_admin user.",
                    ),
                    status=403,
                )

        result = get_user_by_id(
            db=db,
            user_id=canonical_id,
            requesting_user_id=requesting_user_id,
            is_admin=is_admin
        )

        if result.is_success():
            payload = format_user_response(result.data.to_dict(), db=db)
            return BaseController.ok(payload)
        else:
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )
            resp = BaseController.error(error_payload, status=404)
            return resp

    @staticmethod
    def logout(
        request: Request,
        db: Session
    ) -> JSONResponse:
        """
        Hard logout: revoke the access token (jti blacklist) AND clear the
        refresh-token jti on the user row. Idempotent.
        """
        user_id = get_current_user_id(request)
        if not user_id:
            error_payload = format_error_response(
                error_type="authentication_error",
                message="Not authenticated",
            )
            return BaseController.error(error_payload, status=401)

        result = logout_user(
            db=db,
            user_id=user_id,
            token_jti=getattr(request.state, "token_jti", None),
            token_exp=getattr(request.state, "token_exp", None),
        )
        if result.is_success():
            return BaseController.ok(
                format_success_response(result.data["message"])
            )
        error_payload = format_error_response(
            error_type=result.error_type,
            message=result.error,
        )
        return BaseController.error(error_payload, status=500)

    @staticmethod
    def get_me(
        request: Request,
        db: Session
    ) -> JSONResponse:
        """
        Get current user.

        Args:
            request: FastAPI request
            db: Database session

        Returns:
            JSONResponse
        """
        user_id = get_current_user_id(request)

        if not user_id:
            error_payload = format_error_response(
                error_type="authentication_error",
                message="Not authenticated"
            )
            resp = BaseController.error(error_payload, status=401)
            return resp

        result = get_user_by_id(
            db=db,
            user_id=user_id,
            requesting_user_id=user_id,
            is_admin=True  # Users can always view themselves
        )

        if result.is_success():
            payload = format_user_response(result.data.to_dict(), db=db)
            resp = BaseController.ok(payload)
            return resp
        else:
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )
            resp = BaseController.error(error_payload, status=404)
            return resp

    @staticmethod
    def list(
        request: Request,
        query: UserListQuery,
        db: Session
    ) -> JSONResponse:
        """
        List users.

        Args:
            request: FastAPI request
            query: Query parameters
            db: Database session

        Returns:
            JSONResponse
        """
        is_admin = getattr(request.state, "is_admin", False)
        # Doc 44 round 7 — vendor scope for non-admin callers.
        # admin / super_admin (request.state.is_admin == True) see
        # every user. Lower tiers (org_admin / project_admin) see
        # only users in their own vendor (users.vendor_id == caller's
        # vendor_id). project_member doesn't have users:read at all
        # so they can't reach this route.
        vendor_id_filter: Optional[str] = None
        if not is_admin:
            caller_id = get_current_user_id(request)
            caller = (
                UserRepository(db).get_by_id(caller_id)
                if caller_id else None
            )
            if caller is not None and getattr(caller, "vendor_id", None):
                vendor_id_filter = caller.vendor_id
            else:
                # Non-admin caller without a vendor mapping → empty
                # listing (rather than the everyone-cross-vendor view
                # we returned pre-round-7).
                vendor_id_filter = "__no_vendor_assigned__"

        result = list_users(
            db=db,
            page=query.offset,
            page_size=query.pageSize,
            status=query.status,
            is_admin=is_admin,
            include_deleted=getattr(query, "includeDeleted", False),
            vendor_id_filter=vendor_id_filter,
            # Doc 46 round 10 #6 / #13 — non-admin callers (org_admin /
            # project_admin) must not see PMIS-Admin / Super-Admin
            # users in their listing or dropdown sources. The
            # is_admin bypass keeps admin views unchanged.
            exclude_admin_tier=not is_admin,
        )

        if result.is_success():
            paginated = result.data
            user_dicts = [user.to_dict() for user in paginated.items]

            payload = format_collection_response(
                items=user_dicts,
                total=paginated.total,
                page=paginated.page,
                page_size=paginated.page_size,
                collection_type="users",
                db=db,
            )
            resp = BaseController.ok(payload)
            return resp
        else:
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )
            status_code = 422 if result.error_type == "validation_error" else 500
            resp = BaseController.error(error_payload, status=status_code)
            return resp

    @staticmethod
    def update(
        request: Request,
        user_id,
        data: UserUpdateRequest,
        db: Session
    ) -> JSONResponse:
        """
        Update user.

        Args:
            request: FastAPI request
            user_id: User ID — accepts integer ``id`` or ``US-...`` code
                (doc 25).
            data: Update data
            db: Database session

        Returns:
            JSONResponse
        """
        requesting_user_id = get_current_user_id(request)
        is_admin = getattr(request.state, "is_admin", False)
        # Doc 44 round 5 — status-flip authority can come from either
        # is_admin (legacy: admin / super_admin) OR a dedicated
        # ``users:deactivate`` perm held by org_admin / project_admin.
        held_perms = getattr(request.state, "user_permissions", set()) or set()
        can_change_status = is_admin or "users:deactivate" in held_perms

        canonical_id = _resolve_user_id(db, user_id)
        if canonical_id is None:
            return BaseController.error(
                format_error_response(
                    error_type="not_found",
                    message=f"User with ID {user_id} not found",
                ),
                status=404,
            )

        result = update_user(
            db=db,
            user_id=canonical_id,
            email=data.email,
            first_name=data.firstName,
            last_name=data.lastName,
            admin=data.admin,
            status=data.status,
            vendor_id=data.vendorId,
            division=data.division,
            division_other=data.divisionOther,
            phone_number=data.phoneNumber,
            requesting_user_id=requesting_user_id,
            is_admin=is_admin,
            can_change_status=can_change_status,
        )

        if not result.is_success():
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )

            if result.error_type == "not_found":
                status_code = 404
            elif result.error_type == "authorization_error":
                status_code = 403
            elif result.error_type == "validation_error":
                status_code = 422
            else:
                status_code = 500

            return BaseController.error(error_payload, status=status_code)

        # Doc 44 round 9 — apply projectIds replacement after the user-
        # field update succeeds. ``None`` is a no-op; ``[]`` clears;
        # non-empty replaces. Caller-vs-target gate fires per grant /
        # revoke. The helper flushes; we commit below.
        if data.projectIds is not None:
            from .services.replace_project_membership import (
                replace_user_project_membership,
            )
            membership_result = replace_user_project_membership(
                db=db,
                user_id=canonical_id,
                project_ids=data.projectIds,
                caller_id=requesting_user_id,
            )
            if not membership_result.is_success():
                db.rollback()
                error_payload = format_error_response(
                    error_type=membership_result.error_type,
                    message=membership_result.error,
                    details=membership_result.details,
                )
                status_code = (
                    403 if membership_result.error_type == "authorization_error"
                    else 422
                )
                return BaseController.error(error_payload, status=status_code)
            db.commit()

            # Re-hydrate the user so the response carries the updated
            # projects[] / projectAssignments[] arrays.
            from ....infrastructure.db.repositories.user_repository import (
                UserRepository,
            )
            refreshed = UserRepository(db).get_by_id(canonical_id)
            if refreshed is not None:
                payload = format_user_response(refreshed.to_dict(), db=db)
                return BaseController.ok(payload)

        payload = format_user_response(result.data.to_dict(), db=db)
        return BaseController.ok(payload)

    @staticmethod
    def update_password(
        request: Request,
        user_id,
        data: UserPasswordUpdateRequest,
        db: Session
    ) -> JSONResponse:
        """
        Update user password.

        Args:
            request: FastAPI request
            user_id: User ID — accepts integer ``id`` or ``US-...`` code
                (doc 25).
            data: Password update data
            db: Database session

        Returns:
            JSONResponse
        """
        requesting_user_id = get_current_user_id(request)
        is_admin = getattr(request.state, "is_admin", False)

        canonical_id = _resolve_user_id(db, user_id)
        if canonical_id is None:
            return BaseController.error(
                format_error_response(
                    error_type="not_found",
                    message=f"User with ID {user_id} not found",
                ),
                status=404,
            )

        result = update_password(
            db=db,
            user_id=canonical_id,
            new_password=data.password,
            requesting_user_id=requesting_user_id,
            is_admin=is_admin
        )

        if result.is_success():
            payload = format_success_response("Password updated successfully")
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
            elif result.error_type == "authorization_error":
                status_code = 403
            elif result.error_type == "validation_error":
                status_code = 422
            else:
                status_code = 500

            resp = BaseController.error(error_payload, status=status_code)
            return resp

    @staticmethod
    def delete(
        request: Request,
        user_id,
        db: Session
    ) -> JSONResponse:
        """
        Delete user.

        Args:
            request: FastAPI request
            user_id: User ID — accepts integer ``id`` or ``US-...`` code
                (doc 25).
            db: Database session

        Returns:
            JSONResponse
        """
        actor_id = get_current_user_id(request)

        canonical_id = _resolve_user_id(db, user_id)
        if canonical_id is None:
            return BaseController.error(
                format_error_response(
                    error_type="not_found",
                    message=f"User with ID {user_id} not found",
                ),
                status=404,
            )

        result = delete_user(db=db, user_id=canonical_id, actor_id=actor_id)

        if result.is_success():
            payload = format_success_response(
                f"User {canonical_id} deleted successfully"
            )
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
            elif result.error_type == "authorization_error":
                status_code = 403
            elif result.error_type == "validation_error":
                status_code = 422
            else:
                status_code = 500
            resp = BaseController.error(error_payload, status=status_code)
            return resp

    @staticmethod
    def restore(
        request: Request,
        user_id,
        db: Session
    ) -> JSONResponse:
        """
        Restore a soft-deleted user.

        Mirrors POST /vendors/{id}/restore. Idempotent on already-active
        users (returns 200 with the current snapshot).

        Requires: USERS_DELETE_ALL permission (admin only)
        """
        requesting_user_id = get_current_user_id(request)
        is_admin = getattr(request.state, "is_admin", False)

        # Resolve ``user_id`` (integer id OR ``US-...`` code, doc 25) with
        # ``include_deleted`` so we can restore tombstoned rows. The
        # repository's ``resolve_id`` filters out deleted rows for code
        # input — bypass it for the restore path.
        repo = UserRepository(db)
        u = repo.get_by_id_or_code(user_id, include_deleted=True)
        if u is None:
            return BaseController.error(
                format_error_response(
                    error_type="not_found",
                    message=f"User with ID {user_id} not found",
                ),
                status=404,
            )
        canonical_id = u.id

        result = restore_user(
            db=db,
            user_id=canonical_id,
            requesting_user_id=requesting_user_id,
            is_admin=is_admin,
        )

        if result.is_success():
            payload = format_user_response(result.data.to_dict(), db=db)
            return BaseController.ok(payload)
        else:
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details,
            )
            if result.error_type == "not_found":
                status_code = 404
            elif result.error_type == "authorization_error":
                status_code = 403
            else:
                status_code = 500
            return BaseController.error(error_payload, status=status_code)

    @staticmethod
    def login(
        data: LoginRequest,
        db: Session
    ) -> JSONResponse:
        """
        Authenticate user and return token.

        Doc 33 change 3 — 2FA gate: if the user has 2FA enabled (and
        the global ``REQUIRE_2FA`` setting allows it), this endpoint
        returns an ephemeral session token + the available channels
        instead of the access token. The client then calls
        ``/login/send-otp`` to receive an OTP and ``/login/verify-otp``
        to mint the real JWT pair.

        Args:
            data: Login credentials
            db: Database session

        Returns:
            JSONResponse
        """
        result = authenticate_user(
            db=db,
            login=data.login,
            password=data.password
        )

        if result.is_success():
            token_data = result.data
            # Doc 33 change 3: 2FA gate.
            from ....infrastructure.db.repositories.user_repository import UserRepository
            from .services.two_factor import begin_otp_challenge, is_2fa_required_for
            user_obj = token_data.get("user")
            if user_obj is not None and is_2fa_required_for(user_obj):
                challenge = begin_otp_challenge(db, user_obj)
                if challenge.is_success():
                    # Return a 200 with requires_otp=True. No JWT minted
                    # yet — client must call /login/send-otp + /login/verify-otp.
                    payload = {
                        "_type": "LoginOtpRequired",
                        "requires_otp": True,
                        "ephemeral_token": challenge.data["ephemeral_token"],
                        "channels_available": challenge.data["channels_available"],
                        "message": (
                            "Two-factor authentication required. "
                            "Call /users/login/send-otp with the "
                            "ephemeral_token and a chosen channel."
                        ),
                    }
                    return BaseController.ok(payload)
            # Decode the freshly-minted tokens to surface their expiry /
            # issued-at timestamps to the FE. Lets the client schedule a
            # preemptive refresh without having to decode the JWT itself.
            from .services.refresh import _exp_metadata
            access_meta = _exp_metadata(token_data["access_token"])
            refresh_meta = (
                _exp_metadata(token_data["refresh_token"])
                if token_data.get("refresh_token") else {}
            )
            # Keep HAL+JSON for the user inside the `data` payload.
            response_payload = {
                "_type": "Login",
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token"),
                "token_type": token_data["token_type"],
                "accessTokenExpiresAt": access_meta.get("expiresAt"),
                "accessTokenIssuedAt": access_meta.get("issuedAt"),
                "refreshTokenExpiresAt": refresh_meta.get("expiresAt"),
                "refreshTokenIssuedAt": refresh_meta.get("issuedAt"),
                "expiresInSeconds": (
                    int(access_meta["exp"] - access_meta["iat"])
                    if access_meta.get("exp") and access_meta.get("iat") else None
                ),
                "user": format_user_response(token_data["user"].to_dict(), db=db),
            }
            # Opt-in envelope using BaseController helper which calls `api_response()` internally.
            resp = BaseController.ok(response_payload)
            return resp
        else:
            error_response = format_error_response(
                error_type=result.error_type,
                message=result.error,
                details=result.details
            )
            resp = BaseController.error(error_response, status=401)
            return resp

    @staticmethod
    def send_otp(data, db: Session) -> JSONResponse:
        """Doc 33 change 3 — POST /users/login/send-otp."""
        from .services.two_factor import send_or_resend_otp
        from ....shared.otp import hash_secret
        # Map ephemeral_token → user_id by looking it up.
        from ....infrastructure.db.models.otp_code import OtpCodeModel
        # First-time send: no row exists yet. We need to fish out the
        # user_id from the recently-issued ephemeral token. The token
        # itself is opaque — but the login flow stamped its hash onto a
        # Login response and the FE passes it back here. We honor either
        # path:
        #   (a) an existing OtpCode row already exists for this token →
        #       pick the user_id from there (resend path).
        #   (b) no row yet → we need to look up the user. Approach: the
        #       ephemeral_token only appears on a successful login
        #       response, and the FE stores it client-side. We DO NOT
        #       have a server-side mapping from token to user yet, so
        #       we must add one. Easiest: a tiny in-memory cache keyed
        #       by hash, but that doesn't survive restarts. Instead,
        #       the login controller already created a sentinel
        #       OtpCodeModel row with consumed_at=now and user_id set
        #       so we can resolve here even before any code is sent.
        # Implementation note: we sidestep the bookkeeping by stamping
        # a sentinel OTP row at /login (consumed=True, no code generated).
        # See login() above where this is wired.
        token_hash = hash_secret(data.ephemeral_token)
        sentinel = (
            db.query(OtpCodeModel)
            .filter(OtpCodeModel.ephemeral_token_hash == token_hash)
            .order_by(OtpCodeModel.id.desc())
            .first()
        )
        if sentinel is None:
            return BaseController.error(
                format_error_response(
                    "invalid_credentials",
                    "Invalid or expired ephemeral session.",
                ),
                status=401,
            )
        result = send_or_resend_otp(
            db, user_id=sentinel.user_id,
            ephemeral_token=data.ephemeral_token,
            channel=data.channel,
        )
        if not result.is_success():
            err_status = 429 if result.error_type == "cooldown" else (
                422 if result.error_type == "validation_error" else 401
            )
            return BaseController.error(
                format_error_response(
                    result.error_type, result.error, details=result.details,
                ),
                status=err_status,
            )
        payload = {"_type": "OtpSent", **result.data}
        return BaseController.ok(payload)

    @staticmethod
    def verify_otp(data, db: Session) -> JSONResponse:
        """Doc 33 change 3 — POST /users/login/verify-otp.

        On success returns the same shape as a regular /login response
        (access + refresh tokens + user object + expiry metadata).
        """
        from .services.two_factor import verify_otp
        result = verify_otp(
            db, ephemeral_token=data.ephemeral_token, code=data.code,
        )
        if not result.is_success():
            return BaseController.error(
                format_error_response(
                    result.error_type, result.error, details=result.details,
                ),
                status=401,
            )
        token_data = result.data
        # Same response shape as regular login.
        from .services.refresh import _exp_metadata
        access_meta = _exp_metadata(token_data["access_token"])
        refresh_meta = _exp_metadata(token_data["refresh_token"])
        payload = {
            "_type": "Login",
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "token_type": token_data["token_type"],
            "accessTokenExpiresAt": access_meta.get("expiresAt"),
            "accessTokenIssuedAt": access_meta.get("issuedAt"),
            "refreshTokenExpiresAt": refresh_meta.get("expiresAt"),
            "refreshTokenIssuedAt": refresh_meta.get("issuedAt"),
            "expiresInSeconds": (
                int(access_meta["exp"] - access_meta["iat"])
                if access_meta.get("exp") and access_meta.get("iat") else None
            ),
            "user": format_user_response(token_data["user"].to_dict(), db=db),
        }
        return BaseController.ok(payload)

    @staticmethod
    def forgot_password(data, db: Session) -> JSONResponse:
        """Doc 33 change 3 — POST /users/forgot-password.

        Always returns 200 (anti-enumeration). The body is identical
        whether the user exists or not."""
        from .services.password_reset import request_password_reset
        result = request_password_reset(
            db, login_or_email=data.login_or_email, channel=data.channel,
        )
        if not result.is_success():
            # Only fires on validation_error (invalid channel) — other
            # cases fall through to the generic 200 response.
            return BaseController.error(
                format_error_response(result.error_type, result.error),
                status=422,
            )
        return BaseController.ok(result.data)

    @staticmethod
    def reset_password(data, db: Session) -> JSONResponse:
        """Doc 33 change 3 — POST /users/reset-password."""
        from .services.password_reset import perform_password_reset
        result = perform_password_reset(
            db, token_or_code=data.token_or_code,
            new_password=data.new_password,
        )
        if not result.is_success():
            err_status = 422 if result.error_type == "validation_error" else 401
            return BaseController.error(
                format_error_response(result.error_type, result.error),
                status=err_status,
            )
        return BaseController.ok(result.data)

    @staticmethod
    def introspect(
        data,
        db: Session
    ) -> JSONResponse:
        """
        Public introspection endpoint. No auth middleware. RFC 7662-style
        read-only: returns token metadata without ever rotating. Use
        POST /users/refresh to rotate.
        """
        from .services.introspect import introspect_tokens

        result = introspect_tokens(
            db=db,
            access_token=data.access_token,
            refresh_token=data.refresh_token,
        )

        if not result.is_success():
            # Only happens for "no token provided" — a 422 from the schema
            # would be cleaner but the body is well-formed JSON, so the
            # service-layer 400 is appropriate.
            error_payload = format_error_response(
                error_type=result.error_type,
                message=result.error,
            )
            status = 422 if result.error_type == "validation_error" else 401
            return BaseController.error(error_payload, status=status)

        payload = result.data
        payload["_type"] = "Introspect"
        return BaseController.ok(payload)

    @staticmethod
    def refresh(
        data,
        db: Session,
    ) -> JSONResponse:
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
            "user": format_user_response(payload["user"].to_dict(), db=db),
        })
