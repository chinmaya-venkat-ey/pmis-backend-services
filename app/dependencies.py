"""FastAPI dependency factories for pmis-contract-management."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.controllers.master_controller import MasterController
from app.core.errors import UnauthorizedError
from app.core.rbac import AUTH_REQUIRED_MESSAGE
from app.db import get_db


# ---------------------------------------------------------------- request state

def get_current_user_id(request: Request) -> str:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
    return uid


def get_optional_current_user_id(request: Request) -> Optional[str]:
    return getattr(request.state, "user_id", None)


def get_caller_is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


# ---------------------------------------------------------------- controllers

def get_master_controller(db: Session = Depends(get_db)) -> MasterController:
    return MasterController(db)
