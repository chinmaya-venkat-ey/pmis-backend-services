"""Routes for SLA image attachments.

Endpoints (all mounted under /api/v3)
-------------------------------------
POST   /sla-masters/{sla_id}/attachments                 multipart upload, 201
GET    /sla-masters/{sla_id}/attachments                 list live attachments
GET    /sla-masters/{sla_id}/attachments/{att_id}        single attachment
PATCH  /sla-masters/{sla_id}/attachments/{att_id}        update caption
POST   /sla-masters/{sla_id}/attachments/{att_id}/refresh-url
                                                         refresh expired download URL
DELETE /sla-masters/{sla_id}/attachments/{att_id}        soft-delete
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.clients import FileStoreUnavailable
from app.controllers.sla_attachment_controller import SlaAttachmentController
from app.core.errors import ServiceUnavailableError
from app.core.response import api_response, hal_collection, hal_resource
from app.dependencies import (
    get_bearer_token,
    get_optional_current_user_id,
    get_sla_attachment_controller,
)
from app.schemas.sla_attachment import SlaAttachmentCaptionUpdate


router = APIRouter(tags=["SLA Attachments"])


def _hal(result) -> dict:
    return hal_resource(
        "SlaAttachment",
        result.model_dump(),
        self_link=(
            f"/api/v3/sla-masters/{result.sla_id}/attachments/{result.id}"
        ),
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post(
    "/sla-masters/{sla_id}/attachments",
    status_code=status.HTTP_201_CREATED,
    summary="Upload an image attachment to an SLA template",
    description=(
        "Multipart upload. Required field `file` (image/png|jpeg|webp|gif). "
        "Optional form field `caption` (max 500 chars). Forwards the bytes "
        "to pmis-file-store; persists the file_id + cached download URL on "
        "contract.sla_attachments."
    ),
)
async def upload_attachment(
    sla_id: str,
    file: UploadFile = File(..., description="Image file (PNG, JPEG, WebP, GIF)."),
    caption: Optional[str] = Form(None, max_length=500),
    ctrl: SlaAttachmentController = Depends(get_sla_attachment_controller),
    user_id: Optional[str] = Depends(get_optional_current_user_id),
    bearer_token: Optional[str] = Depends(get_bearer_token),
):
    # Read the bytes once so we know the size and can hand a BinaryIO
    # to the service. UploadFile.file is a SpooledTemporaryFile (already
    # binary), so we can pass it straight in after a quick size read.
    content = await file.read()
    size = len(content)

    import io as _io
    bio = _io.BytesIO(content)

    try:
        result = ctrl.upload(
            sla_id,
            file_obj=bio,
            filename=file.filename or "attachment",
            mime_type=file.content_type or "",
            size_bytes=size,
            caption=caption,
            uploaded_by=user_id,
            bearer_token=bearer_token,
        )
    except FileStoreUnavailable as exc:
        raise ServiceUnavailableError(
            f"file-store unavailable: {exc}",
            code="file_store_unavailable",
        ) from exc

    return api_response(
        data=_hal(result),
        message=f"Uploaded '{result.original_filename}' to SLA",
        status=201,
    )


# ---------------------------------------------------------------------------
# List + get
# ---------------------------------------------------------------------------

@router.get(
    "/sla-masters/{sla_id}/attachments",
    summary="List image attachments on an SLA",
)
def list_attachments(
    sla_id: str,
    ctrl: SlaAttachmentController = Depends(get_sla_attachment_controller),
):
    items = ctrl.list_for_sla(sla_id)
    elements = [_hal(r) for r in items]
    return api_response(
        data=hal_collection(
            elements,
            total=len(elements),
            page_size=len(elements) or 1,
        ),
        status=200,
    )


@router.get(
    "/sla-masters/{sla_id}/attachments/{attachment_id}",
    summary="Get a single attachment",
)
def get_attachment(
    sla_id: str,  # noqa: ARG001 — path param for symmetry / RBAC
    attachment_id: str,
    ctrl: SlaAttachmentController = Depends(get_sla_attachment_controller),
):
    result = ctrl.get(attachment_id)
    return api_response(data=_hal(result), status=200)


# ---------------------------------------------------------------------------
# Caption update + refresh URL + delete
# ---------------------------------------------------------------------------

@router.patch(
    "/sla-masters/{sla_id}/attachments/{attachment_id}",
    summary="Update an attachment's caption",
)
def patch_attachment(
    sla_id: str,  # noqa: ARG001
    attachment_id: str,
    payload: SlaAttachmentCaptionUpdate,
    ctrl: SlaAttachmentController = Depends(get_sla_attachment_controller),
):
    result = ctrl.update_caption(attachment_id, payload.caption)
    return api_response(data=_hal(result), status=200)


@router.post(
    "/sla-masters/{sla_id}/attachments/{attachment_id}/refresh-url",
    summary="Refresh the cached download URL (call when an image fails to load)",
)
def refresh_url(
    sla_id: str,  # noqa: ARG001
    attachment_id: str,
    ctrl: SlaAttachmentController = Depends(get_sla_attachment_controller),
    bearer_token: Optional[str] = Depends(get_bearer_token),
):
    try:
        result = ctrl.refresh_url(attachment_id, bearer_token=bearer_token)
    except FileStoreUnavailable as exc:
        raise ServiceUnavailableError(
            f"file-store unavailable: {exc}",
            code="file_store_unavailable",
        ) from exc
    return api_response(
        data={
            "id": result.id,
            "file_url": result.file_url,
            "expires_in_seconds": result.expires_in_seconds,
        },
        status=200,
    )


@router.delete(
    "/sla-masters/{sla_id}/attachments/{attachment_id}",
    summary="Soft-delete an attachment (and best-effort soft-delete the filestore object)",
)
def delete_attachment(
    sla_id: str,  # noqa: ARG001
    attachment_id: str,
    ctrl: SlaAttachmentController = Depends(get_sla_attachment_controller),
    bearer_token: Optional[str] = Depends(get_bearer_token),
):
    info = ctrl.delete(attachment_id, bearer_token=bearer_token)
    msg = (
        "Attachment removed"
        if info.get("filestore_removed")
        else "Attachment removed (filestore delete was best-effort)"
    )
    return api_response(data=info, message=msg, status=200)
