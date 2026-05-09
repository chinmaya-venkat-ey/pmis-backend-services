"""Dashboard surface (admin / super_admin only).

Read-only aggregation endpoints under ``/api/v3/dashboard/*`` feeding
the three top-level views (Summary, Project View, Organization View).
None of these endpoints write — they only read live M / A / project /
vendor rows and fold them through the pure derivation module at
``app/shared/dashboard_derive.py``.
"""
from .routes import router

__all__ = ["router"]
