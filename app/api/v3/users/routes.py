"""
User routes - URL definitions with permission bindings.
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session
from .controller import UserController
from .schemas import (
    UserCreateRequest,
    UserUpdateRequest,
    UserPasswordUpdateRequest,
    LoginRequest,
    UserListQuery
)
from .schemas import (
    ForgotPasswordRequest,
    IntrospectRequest,
    OtpSendRequest,
    OtpVerifyRequest,
    RefreshRequest,
    ResetPasswordRequest,
)
from .permissions import (
    USERS_CREATE,
    USERS_READ,
    USERS_READ_ALL,
    USERS_UPDATE,
    USERS_DELETE_ALL
)
from ....core.middleware.rbac import require_permission, require_authenticated
from ....infrastructure.db.session import get_db

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/introspect",
    summary="Introspect tokens (RFC 7662 read-only metadata)",
    description=(
        "Public token introspection. Returns metadata (active, exp, iat, "
        "jti, sub, userId, role, isAdmin) for the supplied access_token "
        "and/or refresh_token. NEVER rotates — use POST /users/refresh "
        "to mint a fresh access + refresh pair from a valid refresh token. "
        "When both tokens are supplied, the response shape becomes "
        "{access: {...}, refresh: {...}}."
    ),
)
def introspect(
    data: IntrospectRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Public introspection endpoint. Accepts tokens in request body."""
    return UserController.introspect(data, db)


@router.post(
    "/refresh",
    summary="Refresh access token (rotates the refresh token too)",
    description=(
        "Validates the supplied refresh token and issues a fresh access + "
        "refresh pair. The user row's stored refresh_token_jti is rotated "
        "atomically — concurrent refreshes with the same token can only "
        "succeed once. Response includes accessTokenExpiresAt + "
        "refreshTokenExpiresAt so the client can schedule the next "
        "preemptive refresh."
    ),
)
def refresh(
    data: RefreshRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Public refresh endpoint."""
    return UserController.refresh(data, db)


@router.post(
    "/login",
    summary="Authenticate user",
    description=(
        "Authenticate user and receive a JWT token. "
        "Doc 33 change 3: when 2FA is required for the user (per-user "
        "flag + global ``REQUIRE_2FA``), this endpoint returns "
        "``{requires_otp: true, ephemeral_token, channels_available}`` "
        "instead of an access_token. The client then calls "
        "``/login/send-otp`` and ``/login/verify-otp``."
    ),
)
def login(
    data: LoginRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Authenticate user and return access token (or trigger 2FA flow).

    No authentication required for this endpoint.
    """
    return UserController.login(data, db)


@router.post(
    "/login/send-otp",
    summary="Send OTP for 2FA login",
    description=(
        "Generate + dispatch a 6-digit OTP for an in-progress 2FA "
        "login session. Pass the ``ephemeral_token`` returned from "
        "``/login`` plus a chosen channel (``email`` or ``sms``). "
        "Resends are rate-limited per ``OTP_RESEND_COOLDOWN_SECONDS`` "
        "(default 60s)."
    ),
)
def send_otp(
    data: OtpSendRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.send_otp(data, db)


@router.post(
    "/login/verify-otp",
    summary="Verify OTP and complete login",
    description=(
        "Verify the OTP sent via ``/login/send-otp`` and mint the real "
        "access + refresh JWT pair. Same response shape as a "
        "non-2FA ``/login`` success. Wrong codes increment a counter; "
        "after ``OTP_MAX_ATTEMPTS`` (default 5) the OTP row is "
        "invalidated and the user must request a new one."
    ),
)
def verify_otp(
    data: OtpVerifyRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.verify_otp(data, db)


@router.post(
    "/forgot-password",
    summary="Request a password-reset link or code",
    description=(
        "Self-service password reset. Body: ``{login_or_email, channel}``. "
        "``email`` channel sends a clickable reset link; ``sms`` sends "
        "a numeric code. ALWAYS returns 200 with a generic message "
        "regardless of whether the account exists (anti-enumeration)."
    ),
)
def forgot_password(
    data: ForgotPasswordRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.forgot_password(data, db)


@router.post(
    "/reset-password",
    summary="Complete a password reset",
    description=(
        "Verify the reset token (URL token from email or 6-digit OTP "
        "from SMS) and set the new password. Tokens are single-use "
        "and expire after ``PASSWORD_RESET_TTL_SECONDS`` (default 1h)."
    ),
)
def reset_password(
    data: ResetPasswordRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.reset_password(data, db)


@router.post(
    "/logout",
    dependencies=[require_authenticated()],
    summary="Logout",
    description=(
        "Hard logout. Revokes the access token (adds its jti to the "
        "blacklist) AND clears the user's refresh-token jti. After this "
        "call, the just-used access token will be rejected by the auth "
        "middleware on every subsequent request, and the refresh token "
        "can no longer mint new access tokens. Idempotent."
    ),
)
def logout(
    request: Request,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Revoke the current session. Requires authentication."""
    return UserController.logout(request, db)


@router.get(
    "/me",
    dependencies=[require_authenticated()],
    summary="Get current user",
    description="Get currently authenticated user"
)
def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get current authenticated user.

    Requires: Authentication
    """
    return UserController.get_me(request, db)


@router.post(
    "/create",
    dependencies=[require_permission(USERS_CREATE)],
    summary="Create user",
    description="Create a new user",
    status_code=201
)
def create_user(
    request: Request,
    data: UserCreateRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Create a new user.

    Requires: USERS_CREATE permission (admin only)
    """
    return UserController.create(request, data, db)


@router.get(
    "",
    dependencies=[require_permission(USERS_READ_ALL)],
    summary="List users",
    description="List all users with pagination"
)
def list_users(
    request: Request,
    offset: int = Query(1, ge=1, description="Page number (1-indexed)"),
    pageSize: int = Query(20, ge=1, le=100, description="Items per page"),
    status: str = Query(None, description="Filter by status"),
    include_deleted: bool = Query(
        False,
        description=(
            "Admin only. When true, soft-deleted users are also returned. "
            "Default false hides them."
        ),
    ),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    List users with pagination.

    Requires: USERS_READ_ALL permission (admin only)
    """
    query = UserListQuery(
        offset=offset,
        pageSize=pageSize,
        status=status,
        include_deleted=include_deleted,
    )
    return UserController.list(request, query, db)


@router.get(
    "/{user_id}",
    dependencies=[require_permission(USERS_READ)],
    summary="Get user",
    description=(
        "Get user by ID. The path param accepts EITHER the integer "
        "``id`` OR the human-readable ``userCode`` "
        "(``US-XXXX-YYMMDDHHMMSS`` — see doc 25). The dispatcher "
        "auto-detects via the ``US-`` prefix."
    ),
)
def get_user(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get user by ID.

    Requires: USERS_READ permission
    - Members can view themselves and active users
    - Admins can view all users
    """
    return UserController.get(request, user_id, db)


@router.patch(
    "/{user_id}",
    dependencies=[require_permission(USERS_UPDATE)],
    summary="Update user",
    description=(
        "Update user details. Path param accepts integer ``id`` or "
        "``US-...`` code (doc 25)."
    ),
)
def update_user(
    request: Request,
    user_id: str,
    data: UserUpdateRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Update user details.

    Requires: USERS_UPDATE permission
    - Members can update themselves (excluding admin flag and status)
    - Admins can update all users
    """
    return UserController.update(request, user_id, data, db)


@router.patch(
    "/{user_id}/password",
    dependencies=[require_permission(USERS_UPDATE)],
    summary="Update user password",
    description=(
        "Update user password. Path param accepts integer ``id`` or "
        "``US-...`` code (doc 25)."
    ),
)
def update_user_password(
    request: Request,
    user_id: str,
    data: UserPasswordUpdateRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Update user password.

    Requires: USERS_UPDATE permission
    - Members can update their own password
    - Admins can update any user's password
    """
    return UserController.update_password(request, user_id, data, db)


@router.delete(
    "/{user_id}",
    dependencies=[require_permission(USERS_DELETE_ALL)],
    summary="Delete user",
    description=(
        "Delete user by ID. Path param accepts integer ``id`` or "
        "``US-...`` code (doc 25)."
    ),
)
def delete_user(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Delete user by ID.

    Requires: USERS_DELETE_ALL permission (admin only)
    """
    return UserController.delete(request, user_id, db)


@router.post(
    "/{user_id}/restore",
    dependencies=[require_permission(USERS_DELETE_ALL)],
    summary="Restore a soft-deleted user (admin)",
    description=(
        "Clears deletedAt/deletedBy and sets status='active' on a "
        "soft-deleted user. Idempotent on already-active users — returns "
        "the current snapshot rather than 409. All project mappings, "
        "vendor association, and division values are preserved on disk "
        "during soft-delete and re-surface automatically. Mirrors "
        "POST /api/v3/vendors/{id}/restore. Path param accepts integer "
        "``id`` or ``US-...`` code (doc 25)."
    ),
)
def restore_user(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Restore a soft-deleted user.

    Requires: USERS_DELETE_ALL permission (admin only)
    """
    return UserController.restore(request, user_id, db)


# ---------------------------------------------------------------------------
# RBAC user-side: roles + direct permissions (doc 21 part B)
# ---------------------------------------------------------------------------
from ....core.base_controller import BaseController
from ....core.permissions import (
    ADMIN_ROLE_NAME,
    PERMISSIONS_READ,
    RBAC_ASSIGN,
)
from ....core.response import format_error_response
from ....infrastructure.db.repositories.rbac_repository import RbacRepository
from ....infrastructure.db.repositories.user_repository import UserRepository


def _get_user_or_404(db: Session, user_id):
    """Polymorphic fetch — accepts integer id, numeric string, or
    ``US-...`` code. Returns ``None`` for any unresolvable input.
    Doc 25.
    """
    return UserRepository(db).get_by_id_or_code(user_id)


def _resolve_user_id(db: Session, user_id) -> Optional[int]:
    """Resolve either an int / numeric string or ``US-...`` code to the
    canonical integer ``id``. Returns ``None`` if a code is given that
    doesn't resolve to a live user. Doc 25.
    """
    return UserRepository(db).resolve_id(user_id)


def _serialize_role(r) -> Dict[str, Any]:
    return {
        "_type": "Role",
        "_links": {"self": {"href": f"/api/v3/roles/{r.id}"}},
        "id": r.id,
        "name": r.name,
        "description": getattr(r, "description", None),
        "builtin": r.builtin,
    }


@router.get(
    "/me/permissions",
    dependencies=[require_authenticated()],
    summary="Effective permissions for the current user",
)
def get_my_permissions(
    request: Request, db: Session = Depends(get_db),
):
    """Returns the caller's effective permission set + admin flag.

    Used by the FE to decide which UI actions to show. Requires only
    authentication — no separate permission to read your own grants.
    """
    user_id = getattr(request.state, "user_id", None)
    repo = RbacRepository(db)
    perms = sorted(repo.effective_permissions_for_user(user_id))
    is_admin = repo.user_has_admin_role(user_id)
    return BaseController.ok(data={
        "_type": "EffectivePermissions",
        "userId": user_id,
        "permissions": perms,
        "isAdmin": is_admin,
    })


@router.get(
    "/{user_id}/permissions",
    dependencies=[require_permission(PERMISSIONS_READ)],
    summary="Effective permissions for a user (role-derived ∪ direct)",
)
def get_user_permissions(
    request: Request, user_id: str, db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    if user is None:
        return BaseController.error(
            format_error_response("not_found", f"User {user_id} not found."),
            status=404,
        )
    canonical_id = user.id
    repo = RbacRepository(db)
    return BaseController.ok(data={
        "_type": "EffectivePermissions",
        "userId": canonical_id,
        "permissions": sorted(repo.effective_permissions_for_user(canonical_id)),
        "directPermissions": repo.list_direct_permissions_for_user(canonical_id),
        "isAdmin": repo.user_has_admin_role(canonical_id),
    })


@router.post(
    "/{user_id}/permissions/{code}",
    dependencies=[require_permission(RBAC_ASSIGN)],
    summary="Grant a direct permission to a user",
)
def grant_user_permission(
    request: Request, user_id: str, code: str,
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    if user is None:
        return BaseController.error(
            format_error_response("not_found", f"User {user_id} not found."),
            status=404,
        )
    canonical_id = user.id
    repo = RbacRepository(db)
    if repo.get_permission(code) is None:
        return BaseController.error(
            format_error_response(
                "not_found", f"Permission {code} not found.",
            ),
            status=404,
        )
    actor_id = getattr(request.state, "user_id", None)
    repo.grant_permission_to_user(canonical_id, code, actor_id=actor_id)
    db.commit()
    return BaseController.ok(data={
        "userId": canonical_id,
        "directPermissions": repo.list_direct_permissions_for_user(canonical_id),
    })


@router.delete(
    "/{user_id}/permissions/{code}",
    dependencies=[require_permission(RBAC_ASSIGN)],
    summary="Revoke a direct permission from a user",
)
def revoke_user_permission(
    request: Request, user_id: str, code: str,
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    if user is None:
        return BaseController.error(
            format_error_response("not_found", f"User {user_id} not found."),
            status=404,
        )
    RbacRepository(db).revoke_permission_from_user(user.id, code)
    db.commit()
    return BaseController.no_content()


@router.get(
    "/{user_id}/roles",
    dependencies=[require_permission(PERMISSIONS_READ)],
    summary=(
        "List a user's roles "
        "(DEPRECATED — use GET /api/v3/users/{id}/role-assignments for "
        "the doc-41 scoped view; this endpoint returns only legacy global "
        "roles from user_roles)"
    ),
    description=(
        "**Deprecated**. Returns only the legacy global roles a user holds "
        "(rows in `user_roles`). Doc 41 introduced scoped role assignments "
        "in `user_role_assignments`, which this endpoint does not surface.\n\n"
        "**Use instead**: `GET /api/v3/users/{id}/role-assignments`. That "
        "endpoint returns global, org-scoped, and project-scoped grants "
        "in one list with their scope key per row.\n\n"
        "The response carries `Deprecation: true` and "
        "`Link: </api/v3/users/{id}/role-assignments>; rel=\"successor-version\"` "
        "so DevTools / API clients can highlight migration targets."
    ),
)
def list_user_roles(
    request: Request, user_id: str, db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    if user is None:
        return BaseController.stamp_deprecation(
            BaseController.error(
                format_error_response("not_found", f"User {user_id} not found."),
                status=404,
            ),
            successor_path=f"/api/v3/users/{user_id}/role-assignments",
        )
    rows = RbacRepository(db).list_roles_for_user(user.id)
    return BaseController.stamp_deprecation(
        BaseController.ok(data={
            "_type": "Collection",
            "userId": user.id,
            "count": len(rows),
            "_embedded": {"elements": [_serialize_role(r) for r in rows]},
        }),
        successor_path=f"/api/v3/users/{user.id}/role-assignments",
    )


@router.post(
    "/{user_id}/roles/{role_id}",
    dependencies=[require_permission(RBAC_ASSIGN)],
    summary=(
        "Assign a role to a user (DEPRECATED — use POST /api/v3/users/"
        "{id}/role-assignments for scoped assignments)"
    ),
    description=(
        "**Deprecated**. Writes a global-scope grant to the legacy "
        "`user_roles` table. Doc 41 introduced scope (org / project) on "
        "role assignments via `user_role_assignments` — this endpoint "
        "predates that and cannot express scope.\n\n"
        "**Use instead**: `POST /api/v3/users/{id}/role-assignments` with "
        "body `{ roleId, organizationId?, projectId? }`. Both scope "
        "fields omitted ⇒ global (equivalent to this endpoint's effect). "
        "Caller-vs-target gate enforced server-side."
    ),
)
def assign_user_role(
    request: Request, user_id: str, role_id: int,
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    if user is None:
        return BaseController.stamp_deprecation(
            BaseController.error(
                format_error_response("not_found", f"User {user_id} not found."),
                status=404,
            ),
            successor_path=f"/api/v3/users/{user_id}/role-assignments",
        )
    canonical_id = user.id
    repo = RbacRepository(db)
    if repo.get_role(role_id) is None:
        return BaseController.stamp_deprecation(
            BaseController.error(
                format_error_response("not_found", f"Role {role_id} not found."),
                status=404,
            ),
            successor_path=f"/api/v3/users/{canonical_id}/role-assignments",
        )
    actor_id = getattr(request.state, "user_id", None)
    repo.assign_role_to_user(canonical_id, role_id, actor_id=actor_id)
    db.commit()
    return BaseController.stamp_deprecation(
        BaseController.ok(data={
            "userId": canonical_id,
            "roles": [_serialize_role(r) for r in repo.list_roles_for_user(canonical_id)],
        }),
        successor_path=f"/api/v3/users/{canonical_id}/role-assignments",
    )


@router.delete(
    "/{user_id}/roles/{role_id}",
    dependencies=[require_permission(RBAC_ASSIGN)],
    summary=(
        "Unassign a role from a user (DEPRECATED — use DELETE /api/v3/"
        "users/{id}/role-assignments/{aid}; lockout-protected for 'admin')"
    ),
    description=(
        "**Deprecated**. Revokes the legacy global `user_roles` grant. "
        "Doc 41's `user_role_assignments` rows are NOT affected by this "
        "endpoint — only the legacy table.\n\n"
        "**Use instead**: `DELETE /api/v3/users/{id}/role-assignments/"
        "{assignment_id}`. That path covers both legacy-equivalent "
        "(global) grants and the new org/project-scoped grants and "
        "carries the same lockout protection (last super_admin / admin "
        "cannot be revoked)."
    ),
)
def unassign_user_role(
    request: Request, user_id: str, role_id: int,
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    if user is None:
        return BaseController.error(
            format_error_response("not_found", f"User {user_id} not found."),
            status=404,
        )
    canonical_id = user.id
    repo = RbacRepository(db)
    role = repo.get_role(role_id)
    successor = f"/api/v3/users/{canonical_id}/role-assignments"
    if role is None:
        return BaseController.stamp_deprecation(
            BaseController.error(
                format_error_response("not_found", f"Role {role_id} not found."),
                status=404,
            ),
            successor_path=successor,
        )
    # Lockout: removing the last live admin is rejected.
    if role.name == ADMIN_ROLE_NAME:
        currently_holding = repo.user_has_admin_role(canonical_id)
        if currently_holding and repo.count_users_with_role(role_id) <= 1:
            return BaseController.stamp_deprecation(
                BaseController.error(
                    format_error_response(
                        "forbidden",
                        "Cannot remove the last user holding the 'admin' role. "
                        "Assign 'admin' to another user before removing it from "
                        "this one.",
                    ),
                    status=403,
                ),
                successor_path=successor,
            )
    repo.unassign_role_from_user(canonical_id, role_id)
    db.commit()
    return BaseController.stamp_deprecation(
        BaseController.no_content(),
        successor_path=successor,
    )
