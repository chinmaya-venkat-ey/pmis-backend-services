"""Router composer for pmis-contract-management.

Business routers mount under ``/api/v3``. Health probes live at the app root.
"""
from __future__ import annotations

from fastapi import APIRouter

contract_router = APIRouter(prefix="/api/v3")

# Routes are included here as each phase is implemented.
# Example (Phase 1):
#   from app.routes import contract_routes, sla_routes, formula_routes
#   contract_router.include_router(contract_routes.router)
