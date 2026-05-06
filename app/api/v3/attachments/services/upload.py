"""Upload a standalone attachment (doc 35: thin wrapper over create_comment).

Pre-doc-34 this wrote a row in the separate ``attachments`` table.
After doc 35 the table is gone — every attachment lives on a comment
row. So a "standalone" attachment is just a comment row with no body.

Keeping the same endpoint URL (``POST /<entity>/{id}/attachments``)
and the same single-file shape preserves the FE contract; under the
hood we forward into ``create_comment``.
"""
from fastapi import UploadFile
from sqlalchemy.orm import Session

from .....domain.comments.comment import Comment
from .....shared.service_result import ServiceResult

from ...comments.services import create_comment


def upload_standalone_attachment(
    db: Session,
    *,
    target_kind: str,
    target_id: str,
    upload: UploadFile,
    uploaded_by_user_id: str,
) -> ServiceResult[Comment]:
    """Create a comment row with no body and exactly one attachment.

    Returns the resulting ``Comment`` (the controller formats it via
    ``format_attachment_response`` so the wire shape stays the same as
    pre-doc-34 for FE compatibility).
    """
    if upload is None or upload.filename is None:
        return ServiceResult.fail(
            error="No file uploaded.",
            error_type="validation_error",
        )
    return create_comment(
        db=db,
        target_kind=target_kind,
        target_id=target_id,
        body=None,
        files=[upload],
        author_user_id=uploaded_by_user_id,
    )
