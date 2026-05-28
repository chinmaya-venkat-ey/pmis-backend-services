"""Router composer for pmis-contract-management.

Business routers mount under ``/api/v3``. Health probes live at the app root.
"""
from __future__ import annotations

from fastapi import APIRouter

contract_router = APIRouter(prefix="/api/v3")

from app.routes import master_routes  # noqa: E402
from app.routes import sla_routes  # noqa: E402
from app.routes import sla_activity_mapping_routes  # noqa: E402

contract_router.include_router(master_routes.router)
contract_router.include_router(sla_routes.router)
contract_router.include_router(sla_activity_mapping_routes.router)
