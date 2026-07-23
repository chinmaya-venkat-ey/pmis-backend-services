"""#323 — document access-control management routes (superadmin/admin only).

Mounted under ``/api/v3``:
  * GET ``/documents/access?targetKind=&targetId=``   list a target's documents
       (newest-first) with each document's current access state (the menu).
  * GET ``/documents/{commentId}/access``             one document's rules.
  * PUT ``/documents/{commentId}/access``             set/replace/clear rules.

All three are gated on ``projects:admin_override`` (held by admin / super_admin
only) — the same capability that grants the broad project view. Enforcement of
the stored rules on the read side lives in ``app/services/document_access.py``.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.permissions import PROJECTS_ADMIN_OVERRIDE
from app.core.rbac import require_permission
from app.dependencies import get_current_user_id, get_document_access_controller
from app.schemas.document_access import (
    DocumentAccessList,
    DocumentAccessResponse,
    DocumentAccessUpdateRequest,
)


router = APIRouter(tags=["document-access"])

_TARGET_KINDS = {"project", "milestone", "activity", "task", "subtask"}


@router.get(
    "/documents/access",
    summary="List a target's documents (newest-first) with access state (admin)",
    dependencies=[Depends(require_permission(PROJECTS_ADMIN_OVERRIDE))],
)
def list_document_access(
    controller: Annotated[object, Depends(get_document_access_controller)],
    target_kind: Annotated[str, Query(alias="targetKind")],
    target_id: Annotated[str, Query(alias="targetId")],
) -> DocumentAccessList:
    return controller.list_access(target_kind, target_id)


@router.get(
    "/documents/{comment_id}/access",
    summary="Get one document's access rules (admin)",
    dependencies=[Depends(require_permission(PROJECTS_ADMIN_OVERRIDE))],
)
def get_document_access(
    comment_id: str,
    controller: Annotated[object, Depends(get_document_access_controller)],
) -> DocumentAccessResponse:
    return controller.get_access(comment_id)


@router.put(
    "/documents/{comment_id}/access",
    summary="Set/replace a document's access rules (admin); empty list = public",
    dependencies=[Depends(require_permission(PROJECTS_ADMIN_OVERRIDE))],
)
def set_document_access(
    comment_id: str,
    payload: DocumentAccessUpdateRequest,
    controller: Annotated[object, Depends(get_document_access_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
) -> DocumentAccessResponse:
    return controller.set_access(
        comment_id, payload, caller_user_id=caller_user_id,
    )
