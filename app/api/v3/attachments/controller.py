"""Attachment controller (doc 35: thin shell over comments).

After doc 35 the attachments table is gone — every attachment lives on
a comment row. This controller preserves the historic endpoint shapes
(POST, GET-list, DELETE) so the FE keeps working without a contract
change, but everything routes through the comments services.

The streaming-download endpoint is removed: clients fetch bytes
directly from the URL stored on the comment row's ``attachments`` JSON
column. The fallback ``/files/{key}`` route in app.main serves bytes
in dev when no external file server is configured.
"""
from fastapi import Request, UploadFile
from fastapi.responses import JSONResponse
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
    upload_standalone_attachment,
)


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
            items = [format_attachment_response(c.to_dict()) for c in paged.items]
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
