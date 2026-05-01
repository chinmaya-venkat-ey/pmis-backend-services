"""Comment controller — orchestrates services into HAL+JSON envelopes."""
from typing import List, Optional

from fastapi import Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.dependencies import get_current_user_id
from ....core.response import (
    format_collection_response,
    format_comment_response,
    format_error_response,
    format_success_response,
)

from .services import create_comment, delete_comment, list_comments


class CommentController:

    @staticmethod
    def create(
        request: Request,
        target_kind: str,
        target_id: str,
        body: str,
        files: Optional[List[UploadFile]],
        db: Session,
    ) -> JSONResponse:
        author_id = get_current_user_id(request)
        if not author_id:
            return BaseController.error(
                format_error_response(
                    error_type="authentication_error",
                    message="Not authenticated",
                ),
                status=401,
            )

        result = create_comment(
            db=db,
            target_kind=target_kind,
            target_id=target_id,
            body=body,
            files=files,
            author_user_id=author_id,
        )
        if result.is_success():
            return BaseController.created(format_comment_response(result.data.to_dict()))
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
        result = list_comments(
            db=db,
            target_kind=target_kind,
            target_id=target_id,
            page=page,
            page_size=page_size,
        )
        if result.is_success():
            paged = result.data
            items = [format_comment_response(c.to_dict()) for c in paged.items]
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
        comment_id: str,
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

        result = delete_comment(
            db=db,
            comment_id=comment_id,
            actor_id=actor_id,
            actor_is_admin=actor_is_admin,
        )
        if result.is_success():
            return BaseController.ok(
                format_success_response(f"Comment {comment_id} deleted."),
            )
        return _map_error(result)


# ---- error → HTTP status mapping --------------------------------------

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
