"""Request-state accessors — ported from the monolith."""
from typing import Optional

from fastapi import Request

from .rbac import Role


def get_current_user_id(request: Request) -> Optional[int]:
    return getattr(request.state, "user_id", None)


def get_current_user_role(request: Request) -> Role:
    return getattr(request.state, "user_role", Role.ANONYMOUS)


def get_current_user_login(request: Request) -> Optional[str]:
    return getattr(request.state, "user_login", None)
