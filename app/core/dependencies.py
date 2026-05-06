"""
Core dependencies for dependency injection.

Doc 21 part B: ``get_current_user_role`` was removed — the in-memory
``Role`` enum no longer drives RBAC. Use
``request.state.user_permissions: Set[str]`` (populated by the auth
middleware) when you need to check effective grants from a handler.
"""
from typing import Optional, Set
from fastapi import Request


def get_current_user_id(request: Request) -> Optional[str]:
    """Doc 26: returns the caller's UUID (was int pre-doc-26)."""
    return getattr(request.state, "user_id", None)


def get_current_user_login(request: Request) -> Optional[str]:
    return getattr(request.state, "user_login", None)


def get_current_user_permissions(request: Request) -> Set[str]:
    return getattr(request.state, "user_permissions", set()) or set()


def get_current_user_is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))
