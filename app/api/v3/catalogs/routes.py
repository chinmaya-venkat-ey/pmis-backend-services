"""Catalog routes (LEGACY — superseded by doc 20).

Two read-only endpoints kept here for FE backwards-compat:

- ``GET /api/v3/divisions``                    — division catalog
- ``GET /api/v3/project_status_transitions``   — project lifecycle transitions

Both stamp ``Deprecation: true`` pointing at their ``/api/v3/master/*``
successors. The new master-data router supports full CRUD on these
catalogs; this module is read-only.

The previous ``/api/v3/project_owners`` endpoints (GET, POST /create,
DELETE) were removed entirely in doc 20 — the project_owner whitelist was
already dead since doc 18 made ``project.owner`` a strict division code
rather than a user reference. The repo file and table were dropped in
the same change.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.middleware.rbac import require_authenticated
from ....infrastructure.db.repositories.division_repository import (
    DivisionRepository,
)
from ....infrastructure.db.repositories.project_status_transition_repository import (
    ProjectStatusTransitionRepository,
)
from ....infrastructure.db.session import get_db


router = APIRouter(tags=["catalogs"])


# ---------------------------------------------------------------------------
# Divisions (legacy — read-only)
# ---------------------------------------------------------------------------

@router.get(
    "/divisions",
    dependencies=[require_authenticated()],
    summary="List divisions catalog (DEPRECATED — use /api/v3/master/divisions)",
    description=(
        "Returns the active division entries. Each entry has a `code` "
        "(the wire value the API accepts in `owner` / `division` "
        "fields), a `label`, an `isBuiltin` flag, and a `requiresOther` "
        "flag (true on `others` — tells the FE to show the free-text "
        "'Specify' input). DEPRECATED: use GET /api/v3/master/divisions "
        "which supports admin CRUD too."
    ),
)
def list_divisions(
    request: Request, db: Session = Depends(get_db),
) -> JSONResponse:
    # Always-present built-ins. The catalog's own seed (in init_db) writes
    # the same three rows; this fallback covers test DBs that skip the
    # seed and ensures the FE never sees an empty divisions list.
    builtin_definitions = (
        ("tmd1",   "TMD1",   False),
        ("tmd2",   "TMD2",   False),
        ("others", "Others", True),
    )
    rows = DivisionRepository(db).list_active()
    by_code = {r.code: r for r in rows}

    items = []
    seen = set()
    for code, label, requires_other in builtin_definitions:
        seen.add(code)
        row = by_code.get(code)
        items.append({
            "_type": "Division",
            "code": code,
            "label": (row.label if row else label),
            "isBuiltin": True,
            "requiresOther": requires_other,
        })
    # Append user-added rows (anything in the table that isn't a built-in).
    for r in rows:
        if r.code in seen:
            continue
        items.append({
            "_type": "Division",
            "code": r.code,
            "label": r.label,
            "isBuiltin": bool(r.is_builtin),
            "requiresOther": bool(r.requires_other),
        })

    return BaseController.stamp_deprecation(
        BaseController.ok(data={
            "_type": "Collection",
            "_links": {"self": {"href": "/api/v3/divisions"}},
            "total": len(items),
            "count": len(items),
            "_embedded": {"elements": items},
        }),
        successor_path="/api/v3/master/divisions",
    )


# ---------------------------------------------------------------------------
# Project status transitions (legacy — read-only)
# ---------------------------------------------------------------------------

@router.get(
    "/project_status_transitions",
    dependencies=[require_authenticated()],
    summary=(
        "List project status transition catalog "
        "(DEPRECATED — use /api/v3/master/project_status_transitions)"
    ),
    description=(
        "Returns every active (from_status, to_status) edge plus the "
        "initial-status seed (from_status=null). DEPRECATED: use GET "
        "/api/v3/master/project_status_transitions which supports admin "
        "CRUD too."
    ),
)
def list_project_status_transitions(
    request: Request, db: Session = Depends(get_db),
) -> JSONResponse:
    rows = ProjectStatusTransitionRepository(db).list_active()
    items = [
        {
            "_type": "ProjectStatusTransition",
            "id": r.id,
            "fromStatus": r.from_status,
            "toStatus": r.to_status,
            "requiresAdmin": r.requires_admin,
            "active": r.active,
            "description": r.description,
        }
        for r in rows
    ]
    return BaseController.stamp_deprecation(
        BaseController.ok(data={
            "_type": "Collection",
            "_links": {"self": {"href": "/api/v3/project_status_transitions"}},
            "total": len(items),
            "count": len(items),
            "_embedded": {"elements": items},
        }),
        successor_path="/api/v3/master/project_status_transitions",
    )
