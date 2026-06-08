"""Routes for the authorization decision surface (`/api/v3/authz/*`).

user-svc is the single Policy Decision Point. Consuming services forward
the caller's ``Authorization`` header here and hydrate their request state
from the response, instead of re-resolving permissions from ``users.*``.

`/authz/context` is a normal protected endpoint: the caller's token is
decoded by this service's own AuthMiddleware, so an anonymous/expired/revoked
token yields 401 via ``get_current_user_id``.
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query

from app.controllers.authz_controller import AuthzController
from app.dependencies import (
    get_authz_controller,
    get_caller_vendor_id,
    get_current_user_id,
)
from app.schemas.authz import AuthzContextResponse, AuthzUserSummary


router = APIRouter(prefix="/authz", tags=["authz"])


@router.get(
    "/context",
    response_model=AuthzContextResponse,
    summary="Resolved authorization context for the caller's token",
    description=(
        "Single source of authorization truth. Returns the caller's GLOBAL "
        "flat permission set plus the per-scope code map (project / org / "
        "global, vendor->project projection applied). Consuming services "
        "call this on each request and enforce locally — they no longer "
        "resolve permissions from the users schema themselves."
    ),
    responses={401: {"description": "Anonymous / expired / revoked token"}},
)
def get_context(
    controller: Annotated[AuthzController, Depends(get_authz_controller)],
    user_id: Annotated[str, Depends(get_current_user_id)],
    vendor_id: Annotated[Optional[str], Depends(get_caller_vendor_id)],
):
    return controller.get_context(user_id=user_id, vendor_id=vendor_id)


@router.get(
    "/users",
    response_model=List[AuthzUserSummary],
    summary="Discovery query: users matching an RBAC predicate",
    description=(
        "Returns the RBAC half of a picker / list-scoping query so consuming "
        "services stop reading users.* themselves. Supply EXACTLY ONE of: "
        "`project_id` (project-scoped role holders), `vendor_id` (repeatable; "
        "org-scoped role holders), or `division` (repeatable; users in those "
        "divisions). `role` optionally narrows the project/org selectors; "
        "with `division`, `role` selects users in those divisions who ALSO "
        "hold that role (Bug #226), and `org_id` restricts them to one "
        "organization (users.vendor_id). "
        "`exclude_admin_tier` drops admin/super_admin-tier users. The caller "
        "supplies its own resource facts and unions the results locally."
    ),
    responses={
        401: {"description": "Anonymous / expired / revoked token"},
        422: {"description": "Zero or more than one selector supplied"},
    },
)
def list_users(
    controller: Annotated[AuthzController, Depends(get_authz_controller)],
    _user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: Annotated[Optional[str], Query()] = None,
    vendor_id: Annotated[Optional[List[str]], Query()] = None,
    division: Annotated[Optional[List[str]], Query()] = None,
    role: Annotated[Optional[str], Query()] = None,
    org_id: Annotated[Optional[str], Query()] = None,
    exclude_admin_tier: Annotated[bool, Query()] = False,
):
    return controller.list_users(
        project_id=project_id,
        vendor_ids=vendor_id,
        divisions=division,
        role=role,
        org_id=org_id,
        exclude_admin_tier=exclude_admin_tier,
    )
