"""User routes - URL definitions with permission bindings."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_authenticated, require_permission
from ....infrastructure.db.session import get_db

from .controller import UserController
from .permissions import (
    USERS_CREATE,
    USERS_DELETE_ALL,
    USERS_READ,
    USERS_READ_ALL,
    USERS_UPDATE,
)
from .schemas import (
    IntrospectRequest,
    LoginRequest,
    RefreshRequest,
    UserCreateRequest,
    UserListQuery,
    UserPasswordUpdateRequest,
    UserUpdateRequest,
)


router = APIRouter(prefix="/users", tags=["users"])


# ---- Public -----------------------------------------------------------------

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
def introspect(data: IntrospectRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return UserController.introspect(data, db)


@router.post(
    "/refresh",
    summary="Refresh access token (rotates the refresh token too)",
    description=(
        "Validates the supplied refresh token and issues a fresh access + "
        "refresh pair. The user row's stored refresh_token_jti is rotated "
        "atomically — concurrent refreshes with the same token both succeed "
        "(grace window absorbs the race). Response includes "
        "accessTokenExpiresAt + refreshTokenExpiresAt so the client can "
        "schedule the next preemptive refresh without decoding the JWT."
    ),
)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return UserController.refresh(data, db)


@router.post(
    "/login",
    summary="Authenticate user",
    description="Authenticate user and receive JWT tokens (access + refresh).",
)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return UserController.login(data, db)


# ---- Authenticated ----------------------------------------------------------

@router.post(
    "/logout",
    dependencies=[require_authenticated()],
    summary="Logout (hard revocation)",
    description=(
        "Hard logout. Revokes the access token (adds its jti to the "
        "blacklist) AND clears the user's refresh-token jti. After this "
        "call, the just-used access token will be rejected by the auth "
        "middleware on every subsequent request, and the refresh token "
        "can no longer mint new access tokens. Idempotent."
    ),
)
def logout(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return UserController.logout(request, db)


@router.get(
    "/me",
    dependencies=[require_authenticated()],
    summary="Get current user",
)
def get_current_user(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return UserController.get_me(request, db)


# ---- User CRUD --------------------------------------------------------------

@router.post(
    "/create",
    dependencies=[require_permission(USERS_CREATE)],
    summary="Create user",
    status_code=201,
)
def create_user(
    request: Request, data: UserCreateRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.create(request, data, db)


@router.get(
    "",
    dependencies=[require_permission(USERS_READ_ALL)],
    summary="List users",
)
def list_users(
    request: Request,
    offset: int = Query(1, ge=1, description="Page number (1-indexed)"),
    pageSize: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    include_deleted: bool = Query(
        False,
        description=(
            "Admin only. When true, soft-deleted users are also returned. "
            "Default false hides them."
        ),
    ),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.list(
        request,
        UserListQuery(
            offset=offset,
            pageSize=pageSize,
            status=status,
            include_deleted=include_deleted,
        ),
        db,
    )


@router.get(
    "/{user_id}",
    dependencies=[require_permission(USERS_READ)],
    summary="Get user by id",
)
def get_user(
    request: Request, user_id: int, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.get(request, user_id, db)


@router.patch(
    "/{user_id}",
    dependencies=[require_permission(USERS_UPDATE)],
    summary="Update user",
)
def update_user(
    request: Request, user_id: int,
    data: UserUpdateRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.update(request, user_id, data, db)


@router.patch(
    "/{user_id}/password",
    dependencies=[require_permission(USERS_UPDATE)],
    summary="Update user password",
)
def update_user_password(
    request: Request, user_id: int,
    data: UserPasswordUpdateRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.update_password(request, user_id, data, db)


@router.delete(
    "/{user_id}",
    dependencies=[require_permission(USERS_DELETE_ALL)],
    summary="Delete user (soft-delete)",
)
def delete_user(
    request: Request, user_id: int, db: Session = Depends(get_db),
) -> Dict[str, Any]:
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
        "during soft-delete and re-surface automatically."
    ),
)
def restore_user(
    request: Request, user_id: int, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.restore(request, user_id, db)
