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


# §3.14 (2026-06-02 audit): get_caller_is_admin removed — no route in
# this service consumed it. Re-add when a service-layer admin check is
# wired through a route (and replace with a permission-code check per A1).
