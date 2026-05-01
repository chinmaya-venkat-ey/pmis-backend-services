"""Attachment controller — orchestrates services + builds responses
including the streaming download path.
"""
from urllib.parse import quote

from fastapi import Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.dependencies import get_current_user_id
from ....core.response import (
    format_attachment_response,
    format_error_response,
    format_success_response,
)

from .services import (
    delete_attachment,
    list_standalone_attachments,
    open_attachment_for_download,
    upload_standalone_attachment,
)


_DOWNLOAD_CHUNK = 64 * 1024  # 64 KB


class AttachmentController:

    @staticmethod
    def upload(
        request: Request,
        target_kind: str,
        target_id: str,
        upload: UploadFile,
        db: Session,
    ) -> JSONResponse:
        actor_id = get_current_user_id(request)
        if not actor_id:
            return BaseController.error(
                format_error_response(
                    error_type="authentication_error",
                    message="Not authenticated",
                ),
                status=401,
            )

        result = upload_standalone_attachment(
            db=db,
            target_kind=target_kind,
            target_id=target_id,
            upload=upload,
            uploaded_by_user_id=actor_id,
        )
        if result.is_success():
            return BaseController.created(
                format_attachment_response(result.data.to_dict()),
            )
        return _map_error(result)

    @staticmethod
    def list(
        request: Request,
        target_kind: str,
        target_id: str,
        page: int,
        page_size: int,
        db: Session,
    ) -> JSONResponse:
        result = list_standalone_attachments(
            db=db, target_kind=target_kind, target_id=target_id,
            page=page, page_size=page_size,
        )
        if result.is_success():
            paged = result.data
            items = [format_attachment_response(a.to_dict()) for a in paged.items]
            return BaseController.ok({
                "_type": "Collection",
                "total": paged.total,
                "count": len(items),
                "pageSize": paged.page_size,
                "offset": paged.page,
                "_embedded": {"elements": items},
            })
        return _map_error(result)

    @staticmethod
    def download(
        request: Request,
        attachment_id: str,
        db: Session,
    ):
        """Stream the file bytes back with proper Content-Disposition."""
        result = open_attachment_for_download(db=db, attachment_id=attachment_id)
        if not result.is_success():
            return _map_error(result)

        attachment = result.data["attachment"]
        stream = result.data["stream"]

        def chunk_iter():
            try:
                while True:
                    chunk = stream.read(_DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    yield chunk
            finally:
                stream.close()

        # RFC 5987 — encode the filename so non-ASCII names work.
        safe_name = quote(attachment.original_filename)
        headers = {
            "Content-Disposition": (
                f'attachment; filename="{attachment.original_filename}"; '
                f"filename*=UTF-8''{safe_name}"
            ),
            "Content-Length": str(attachment.size_bytes),
        }
        return StreamingResponse(
            chunk_iter(),
            media_type=attachment.mime_type or "application/octet-stream",
            headers=headers,
        )

    @staticmethod
    def delete(
        request: Request,
        attachment_id: str,
        db: Session,
    ) -> JSONResponse:
        actor_id = get_current_user_id(request)
        if not actor_id:
            return BaseController.error(
                format_error_response(
                    error_type="authentication_error",
                    message="Not authenticated",
                ),
                status=401,
            )
        actor_is_admin = bool(getattr(request.state, "is_admin", False))

        result = delete_attachment(
            db=db,
            attachment_id=attachment_id,
            actor_id=actor_id,
            actor_is_admin=actor_is_admin,
        )
        if result.is_success():
            return BaseController.ok(
                format_success_response(f"Attachment {attachment_id} deleted."),
            )
        return _map_error(result)


_STATUS_BY_ERROR_TYPE = {
    "validation_error": 422,
    "authentication_error": 401,
    "authorization_error": 403,
    "not_found": 404,
    "storage_unavailable": 503,
    "internal_error": 500,
}


def _map_error(result) -> JSONResponse:
    status = _STATUS_BY_ERROR_TYPE.get(result.error_type, 500)
    return BaseController.error(
        format_error_response(
            error_type=result.error_type,
            message=result.error,
            details=result.details,
        ),
        status=status,
    )
