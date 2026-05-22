"""Audit log routes — GET /api/v3/files/audit-logs."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.permissions import FILES_ADMIN, FILES_READ
from app.core.rbac import require_any_permission
from app.controllers.file_controller import FileController
from app.db import get_db
from app.dependencies import get_current_user_id


router = APIRouter(prefix="/files", tags=["audit-logs"])


def _get_controller(db: Session = Depends(get_db)) -> FileController:
    return FileController(db)


@router.get(
    "/audit-logs",
    summary="Fetch file audit logs",
    description=(
        "Returns audit log entries for file operations (upload, download, "
        "delete, restore, search). All query parameters are optional filters. "
        "Requires files:read or files:admin."
    ),
    dependencies=[Depends(require_any_permission(FILES_READ, FILES_ADMIN))],
)
def list_audit_logs(
    file_id: Optional[str] = Query(None, description="Filter by file UUID."),
    action: Optional[str] = Query(
        None,
        description="Filter by action (upload, download, delete, restore, search).",
    ),
    actor_user_id: Optional[str] = Query(None, alias="actorUserId"),
    folder: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None, alias="entityType"),
    entity_id: Optional[str] = Query(None, alias="entityId"),
    offset: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    controller: FileController = Depends(_get_controller),
    caller_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    return controller.search_audit_logs(
        file_id=file_id,
        action=action,
        actor_user_id=actor_user_id,
        folder=folder,
        entity_type=entity_type,
        entity_id=entity_id,
        offset=offset,
        page_size=page_size,
    )
