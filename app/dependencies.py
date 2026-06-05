"""FastAPI DI factories for pmis-user-management."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.controllers.auth_controller import AuthController
from app.controllers.authz_controller import AuthzController
from app.controllers.permission_controller import PermissionController
from app.controllers.role_assignment_controller import RoleAssignmentController
from app.controllers.role_controller import RoleController
from app.controllers.role_grants_controller import RoleGrantsController
from app.controllers.user_controller import UserController
from app.core.rbac import AUTH_REQUIRED_MESSAGE
from app.core.errors import UnauthorizedError
from app.db import get_db
from app.repositories.authz_query_repository import AuthzQueryRepository
from app.repositories.rbac_repository import RbacRepository
from app.services.auth_service import AuthService
from app.services.password_reset_service import PasswordResetService
from app.services.permission_service import PermissionService
from app.services.refresh_service import RefreshService
from app.services.role_assignment_service import RoleAssignmentService
from app.services.role_grants_service import RoleGrantsService
from app.services.role_service import RoleService
from app.services.two_factor_service import TwoFactorService
from app.services.user_service import UserService


# ---------------------------------------------------------------------------
# Controllers
# ---------------------------------------------------------------------------

def get_auth_controller(db: Session = Depends(get_db)) -> AuthController:
    return AuthController(
        auth_service=AuthService(db),
        two_factor_service=TwoFactorService(db),
        refresh_service=RefreshService(db),
        password_reset_service=PasswordResetService(db),
    )


def get_user_controller(db: Session = Depends(get_db)) -> UserController:
    return UserController(
        user_service=UserService(db),
        permission_service=PermissionService(db),
    )


def get_role_controller(db: Session = Depends(get_db)) -> RoleController:
    return RoleController(RoleService(db))


def get_permission_controller(db: Session = Depends(get_db)) -> PermissionController:
    return PermissionController(PermissionService(db))


def get_role_assignment_controller(db: Session = Depends(get_db)) -> RoleAssignmentController:
    return RoleAssignmentController(RoleAssignmentService(db))


def get_role_grants_controller() -> RoleGrantsController:
    return RoleGrantsController(RoleGrantsService())


def get_rbac_repo(db: Session = Depends(get_db)) -> RbacRepository:
    return RbacRepository(db)


def get_authz_controller(db: Session = Depends(get_db)) -> AuthzController:
    return AuthzController(RbacRepository(db), AuthzQueryRepository(db))


# ---------------------------------------------------------------------------
# request.state shortcuts
# ---------------------------------------------------------------------------

def get_current_user_id(request: Request) -> str:
    """401 if no user is bound to the request. Use as Depends in routes that
    need the caller's id."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="AUTH_REQUIRED")
    return user_id


def get_caller_is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


def get_caller_vendor_id(request: Request) -> Optional[str]:
    """The caller's own owning vendor/organization id (hydrated by
    AuthMiddleware), or None. Used to populate the authz context's
    `vendor_id` for row-level vendor scoping in consuming services."""
    return getattr(request.state, "vendor_id", None)


def get_caller_jti(request: Request) -> str:
    return getattr(request.state, "token_jti", "") or ""
