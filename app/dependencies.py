"""FastAPI dependency factories for pmis-contract-management."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.clients import ProjectManagementClient
from app.controllers.master_controller import MasterController
from app.controllers.sla_activity_mapping_controller import (
    SlaActivityMappingController,
)
from app.controllers.sla_controller import SlaController
from app.core.errors import UnauthorizedError
from app.core.rbac import AUTH_REQUIRED_MESSAGE
from app.core.security import extract_bearer_token
from app.db import get_db


# ---------------------------------------------------------------- request state

def get_current_user_id(request: Request) -> str:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
    return uid


def get_optional_current_user_id(request: Request) -> Optional[str]:
    return getattr(request.state, "user_id", None)


# §3.14 (2026-06-02 audit): get_caller_is_admin removed — no route in
# this service consumed it. Re-add when a service-layer admin check is
# wired through a route (and replace with a permission-code check per A1).


def get_bearer_token(request: Request) -> Optional[str]:
    """Extract the raw inbound bearer token so it can be forwarded to peer services.

    Returns None for unauthenticated requests — peer calls then run without
    auth and may be rejected by the upstream's RBAC.
    """
    return extract_bearer_token(request.headers.get("Authorization"))


# ---------------------------------------------------------------- clients

@lru_cache(maxsize=1)
def _project_management_client_singleton() -> ProjectManagementClient:
    return ProjectManagementClient()


def get_project_management_client() -> ProjectManagementClient:
    return _project_management_client_singleton()


# ---------------------------------------------------------------- controllers

def get_master_controller(db: Session = Depends(get_db)) -> MasterController:
    return MasterController(db)


def get_sla_controller(db: Session = Depends(get_db)) -> SlaController:
    return SlaController(db)


def get_sla_activity_mapping_controller(
    db: Session = Depends(get_db),
    project_mgmt_client: ProjectManagementClient = Depends(get_project_management_client),
) -> SlaActivityMappingController:
    return SlaActivityMappingController(db, project_mgmt_client=project_mgmt_client)
