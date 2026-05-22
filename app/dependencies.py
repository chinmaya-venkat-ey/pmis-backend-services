"""FastAPI dependency factories for pmis-file-store."""
from __future__ import annotations

from typing import Optional

from fastapi import Request


def get_current_user_id(request: Request) -> str:
    """Return the authenticated user's ID (hydrated by AuthMiddleware).

    Raises nothing — the auth check is done by require_permission / require_authenticated
    dependency gates on each route.
    """
    return getattr(request.state, "user_id", None) or ""


def get_caller_is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))
