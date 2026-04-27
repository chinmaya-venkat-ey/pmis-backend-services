"""User routes — URL bindings with permission guards.

Ported from the monolith. All 9 endpoints are preserved as-is so client
code works unchanged against this service.
"""
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
    UserCreateRequest,
    UserListQuery,
    UserPasswordUpdateRequest,
    UserUpdateRequest,
)


router = APIRouter(prefix="/users", tags=["users"])


# ---- Public -----------------------------------------------------------------

@router.post(
    "/introspect",
    summary="Introspect tokens",
    description="Public token introspection + refresh rotation endpoint.",
)
def introspect(data: IntrospectRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return UserController.introspect(data, db)


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
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.list(
        request,
        UserListQuery(offset=offset, pageSize=pageSize, status=status),
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
    summary="Delete user",
)
def delete_user(
    request: Request, user_id: int, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return UserController.delete(request, user_id, db)
