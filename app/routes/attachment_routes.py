"""Attachment routes — per-target upload + list + DELETE, plus the
dev-fallback ``/files/{key}`` download.

Per Doc-35 attachments ride on the comments table — uploads create a
``body IS NULL`` comment row. Targets: ``project`` / ``milestone`` /
``activity`` / ``task`` / ``subtask``.

Two routers:

  * ``router`` (under ``/project``):
      POST ``/{plural}/{id}/attachments``   upload one or more files
      GET  ``/{plural}/{id}/attachments``   list attachment rows
      DELETE ``/attachments/{id}``           aliased to comment delete

  * ``files_router`` (mounted at app root by ``app.main``):
      GET ``/files/{storage_key:path}``     dev fallback that streams
      bytes from local storage. Auth-FREE (matches monolith) — URLs are
      UUID-guarded by ``FileStorage.generate_storage_key``, and the
      route is mounted only when ``file_server_local_fallback_enabled``
      is set. In prod the FE fetches from the NFS HTTP front directly.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.controllers.attachment_controller import AttachmentController
from app.core.permissions import (
    ATTACHMENTS_CREATE,
    COMMENTS_READ,
)
from app.core.rbac import assert_action_allowed, require_authenticated
from app.dependencies import (
    get_attachment_controller,
    get_caller_is_admin,
    get_current_user_id,
)
from app.schemas.comment import CommentDeleteSuccess, CommentResponse
from app.utilities.file_storage import StorageError, get_storage
from app.utilities.openapi_extra import multipart_files_only_request_body


def _project_id_for_target(target_kind: str, target_id: str) -> str:
    """(target_kind, target_id) -> project_id via DB lookup. Round-8 scope helper."""
    from app.core.rbac import _ancestor_project_id  # noqa: PLC0415
    return _ancestor_project_id(f"{target_kind}_id", target_id) or ""


# ----- /project/{kind}/{id}/attachments -----------------------------------
router = APIRouter(tags=["attachments"])


# Project attachments live in ``project_routes`` (with their custom
# permission gate + multipart wiring); the factory only handles the
# M/A/T/S targets here.
_KIND_BY_PATH = {
    "milestones": "milestone",
    "activities": "activity",
    "tasks": "task",
    "subtasks": "subtask",
}


def _make_upload_endpoint(target_kind: str):
    # No return annotation on purpose — the handler emits the slim
    # ``{total, elements: [...]}`` shape and the HAL wrapper builds the
    # ``AttachmentList`` envelope around it. Annotating ``Dict[...]``
    # would make FastAPI derive ``_type=Dict`` on the response.
    #
    # Monolith parity: M/A/T/S attachment POST accepts a SINGLE file
    # under the form key ``file`` (singular). Project-attachment POST
    # is the plural ``files`` form — that route lives in
    # ``project_routes`` and is unaffected.
    async def handler(
        target_id: str,
        request: Request,
        controller: Annotated[AttachmentController, Depends(get_attachment_controller)],
        caller_user_id: Annotated[str, Depends(get_current_user_id)],
        file: UploadFile = File(..., description="A file to attach."),
    ):
        # Round-8: resolve parent project_id and scope-check ATTACHMENTS_CREATE.
        project_id = _project_id_for_target(target_kind, target_id)
        assert_action_allowed(
            request,
            code=ATTACHMENTS_CREATE,
            scope_key=("project", project_id) if project_id else None,
        )
        return controller.upload(
            target_kind, target_id, [file],
            caller_user_id=caller_user_id,
        )

    handler.__name__ = f"upload_{target_kind}_attachments"
    return handler


def _make_list_endpoint(target_kind: str):
    def handler(
        target_id: str,
        request: Request,
        controller: Annotated[AttachmentController, Depends(get_attachment_controller)],
        offset: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    ):
        # Round-8: scope-check COMMENTS_READ at the parent project.
        project_id = _project_id_for_target(target_kind, target_id)
        assert_action_allowed(
            request,
            code=COMMENTS_READ,
            scope_key=("project", project_id) if project_id else None,
        )
        # Monolith parity: attachment list always filters out soft-deleted.
        return controller.list_for_target(
            target_kind, target_id,
            offset=offset, page_size=page_size, include_deleted=False,
        )

    handler.__name__ = f"list_{target_kind}_attachments"
    return handler


for _path, _kind in _KIND_BY_PATH.items():
    router.add_api_route(
        f"/{_path}/{{target_id}}/attachments",
        _make_upload_endpoint(_kind),
        methods=["POST"],
        # Round-8: handler does scope-check inline; route gate is just auth.
        dependencies=[Depends(require_authenticated())],
        summary=f"Upload an attachment to a {_kind}",
        description=(
            "Multipart upload (single ``file`` field — monolith parity). "
            "Stored as a comment row with ``body=NULL`` and the file "
            "metadata in the JSON ``attachments`` column. Response is a "
            "full Comment HAL envelope with the file under "
            "``attachments[]``."
        ),
        status_code=status.HTTP_201_CREATED,
        # Monolith parity: M/A/T/S upload returns a Comment HAL envelope,
        # so the wrap layer derives ``_type: "Comment"`` from this model.
        response_model=CommentResponse,
        # Swagger UI 5.x renders a proper file picker only when the
        # request body is declared with ``format: binary`` explicitly.
        openapi_extra=multipart_files_only_request_body(
            field_name="file",
            description=f"A file to attach to the {_kind}.",
        ),
    )
    router.add_api_route(
        f"/{_path}/{{target_id}}/attachments",
        _make_list_endpoint(_kind),
        methods=["GET"],
        # Round-8: handler does scope-check inline.
        dependencies=[Depends(require_authenticated())],
        summary=f"List standalone attachments under a {_kind}",
        description=(
            "Returns body-IS-NULL comment rows for the target, newest-"
            "first. Each entry carries the parent comment id (use with "
            "DELETE /project/attachments/{id})."
        ),
    )


# --------------------------------------------------------- DELETE by id

@router.delete(
    "/attachments/{attachment_id}",
    response_model=CommentDeleteSuccess,
    summary="Soft-delete an attachment (uploader or admin)",
    description=(
        "Aliased to ``DELETE /project/comments/{id}``. The id resolves to "
        "a comment row whose body is NULL. Bytes on disk stay until the "
        "retention cron sweeps them. Monolith parity: response is a "
        "``Success`` envelope with the attachment-specific message "
        "``\"Attachment <uuid> deleted.\"`` (NOT the comment-worded "
        "form)."
    ),
    dependencies=[Depends(require_authenticated())],
)
def delete_attachment(
    request: Request,
    attachment_id: str,
    controller: Annotated[AttachmentController, Depends(get_attachment_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
) -> CommentDeleteSuccess:
    caller_permissions = getattr(request.state, "user_permissions", None) or set()
    return controller.delete(
        attachment_id,
        caller_user_id=caller_user_id,
        caller_is_admin=caller_is_admin,
        caller_permissions=caller_permissions,
    )


# ----- /files/{storage_key:path} (app root, dev fallback, auth-free) ----
files_router = APIRouter(tags=["attachments"])


@files_router.get(
    "/files/{storage_key:path}",
    summary="Serve attachment bytes from local storage (dev fallback, auth-free)",
    description=(
        "Dev-only fallback when ``settings.file_server_public_base_url`` "
        "is empty. Auth-free by design (matches monolith) — URLs embed "
        "an unguessable UUID prefix and the route is only mounted when "
        "``file_server_local_fallback_enabled`` is true. In prod the FE "
        "fetches bytes from the NFS HTTP server directly and this route "
        "is unused."
    ),
    responses={
        404: {"description": "File not found on disk"},
    },
)
def download_file(storage_key: str):
    storage = get_storage()
    try:
        absolute = storage.absolute_path(storage_key)
    except StorageError:
        # Path-traversal attempt or invalid key — 404 to avoid leaking
        # whether the base path exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    if not absolute.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    return FileResponse(path=str(absolute), filename=absolute.name)
