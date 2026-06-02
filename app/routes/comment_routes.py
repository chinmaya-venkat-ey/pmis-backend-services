"""Comment routes — polymorphic comments across 4 targets:
``milestone`` / ``activity`` / ``task`` / ``subtask`` (monolith parity).

Project-level files travel via the dedicated
``POST /project/projects/{uuid}/attachments`` endpoint — there's no
``/projects/{uuid}/comments`` route, matching the monolith.

POST accepts multipart/form-data with optional ``body`` (Form field) and
``files`` (UploadFile entries). Either a non-empty body or at least one
file is required (Doc-35 send-event invariant).

DELETE is open to the comment's author OR any admin / super_admin.
Soft-delete: deleted_at + deleted_by are set; body and attachments are
preserved (reversible).
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status

from app.controllers.comment_controller import CommentController
from app.core.permissions import (
    COMMENTS_CREATE,
    COMMENTS_READ,
)
from app.core.rbac import assert_action_allowed, require_authenticated
from app.dependencies import (
    get_caller_is_admin,
    get_comment_controller,
    get_current_user_id,
)
from app.schemas.comment import CommentDeleteSuccess, CommentResponse
from app.utilities.openapi_extra import multipart_body_and_files_request_body


def _project_id_for_target(target_kind: str, target_id: str) -> str:
    """Resolve (target_kind, target_id) -> project_id via DB lookup.

    Used by the inline scope-check on comment create/list endpoints whose
    URL doesn't carry the project_uuid. Mirrors the ancestor-lookup pattern
    already used by `require_project_permission` for entity-id routes.
    """
    from app.core.rbac import _ancestor_project_id  # noqa: PLC0415
    return _ancestor_project_id(f"{target_kind}_id", target_id) or ""


router = APIRouter(tags=["comments"])


# URL path segment (plural) → internal target_kind (singular).
# Monolith parity: project-level comments don't have their own route —
# project attachments use POST /projects/{uuid}/attachments instead.
_KIND_BY_PATH = {
    "milestones": "milestone",
    "activities": "activity",
    "tasks": "task",
    "subtasks": "subtask",
}


def _make_create_endpoint(target_kind: str):
    """Multipart POST handler factory bound to one target_kind.

    Round-8 scope check: resolves the target's parent project_id and asserts
    the caller holds ``comments:create`` at that project scope (or globally).
    Replaces the previous flat-set ``require_permission(COMMENTS_CREATE)``
    gate which leaked scoped grants across projects.
    """

    async def handler(
        target_id: str,
        request: Request,
        controller: Annotated[CommentController, Depends(get_comment_controller)],
        caller_user_id: Annotated[str, Depends(get_current_user_id)],
        body: str = Form(""),
        files: Optional[List[UploadFile]] = File(None),
    ) -> CommentResponse:
        project_id = _project_id_for_target(target_kind, target_id)
        assert_action_allowed(
            request,
            code=COMMENTS_CREATE,
            scope_key=("project", project_id) if project_id else None,
        )
        return controller.create_multipart(
            target_kind=target_kind,
            target_id=target_id,
            body=body or None,
            files=files or [],
            caller_user_id=caller_user_id,
        )

    handler.__name__ = f"create_{target_kind}_comment"
    return handler


def _make_list_endpoint(target_kind: str):
    """GET handler factory bound to one target_kind.

    Round-8 scope check: same as the create endpoint, but asserts
    ``comments:read`` at the parent project's scope.
    """

    def handler(
        target_id: str,
        request: Request,
        controller: Annotated[CommentController, Depends(get_comment_controller)],
        offset: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    ):
        project_id = _project_id_for_target(target_kind, target_id)
        assert_action_allowed(
            request,
            code=COMMENTS_READ,
            scope_key=("project", project_id) if project_id else None,
        )
        # Monolith parity: comment list always filters out soft-deleted -
        # there's no ``includeDeleted`` toggle on the wire.
        return controller.list_for_target(
            target_kind, target_id,
            offset=offset, page_size=page_size, include_deleted=False,
        )

    handler.__name__ = f"list_{target_kind}_comments"
    return handler


for _path, _kind in _KIND_BY_PATH.items():
    router.add_api_route(
        f"/{_path}/{{target_id}}/comments",
        _make_create_endpoint(_kind),
        methods=["POST"],
        response_model=CommentResponse,
        # Round-8: route gate is just auth; the handler then resolves the
        # parent project_id and asserts COMMENTS_CREATE at that scope.
        dependencies=[Depends(require_authenticated())],
        summary=f"Post a comment on a {_kind} (body and/or files via multipart)",
        description=(
            "Multipart upload. Either a non-empty ``body`` or at least one "
            "file is required. Files are streamed to the file client; "
            "their URL envelopes land on the comment's JSON ``attachments`` "
            "column."
        ),
        status_code=status.HTTP_201_CREATED,
        # Swagger UI needs an explicit multipart schema to render the
        # ``body`` text field + a multi-file picker.
        openapi_extra=multipart_body_and_files_request_body(),
    )
    router.add_api_route(
        f"/{_path}/{{target_id}}/comments",
        _make_list_endpoint(_kind),
        methods=["GET"],
        # Round-8: handler asserts COMMENTS_READ at the parent project scope.
        dependencies=[Depends(require_authenticated())],
        summary=f"List comments on a {_kind} (newest first)",
    )


# --------------------------------------------------------- DELETE by id

@router.delete(
    "/comments/{comment_id}",
    response_model=CommentDeleteSuccess,
    summary="Soft-delete a comment (author or admin)",
    description=(
        "Reversible soft-delete: sets ``deleted_at`` + ``deleted_by`` on "
        "the row; ``body`` and ``attachments`` are preserved for audit. "
        "Only the comment's original author OR an admin / super_admin "
        "may delete. Monolith parity: response is a ``Success`` envelope "
        "(``{_type: 'Success', message: 'Comment <uuid> deleted.'}``), "
        "NOT the full Comment row."
    ),
    dependencies=[Depends(require_authenticated())],
)
def delete_comment(
    request: Request,
    comment_id: str,
    controller: Annotated[CommentController, Depends(get_comment_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
) -> CommentDeleteSuccess:
    caller_permissions = getattr(request.state, "user_permissions", None) or set()
    return controller.delete(
        comment_id,
        caller_user_id=caller_user_id,
        caller_is_admin=caller_is_admin,
        caller_permissions=caller_permissions,
    )
