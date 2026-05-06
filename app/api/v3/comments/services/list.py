"""List-comments service (doc 35: unified send-event model).

One repo call returns rows + their JSON-embedded attachments. No
separate hydrate-attachments-per-comment loop — the data lives on the
row.

Newest-first, paginated. Soft-deleted rows are filtered out by default.
"""
from typing import Optional

from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.comment_repository import (
    CommentRepository,
)
from .....shared.pagination import PaginatedResult, calculate_offset
from .....shared.service_result import ServiceResult

from .._target_helper import is_valid_target_kind, target_exists


def list_comments(
    db: Session,
    *,
    target_kind: str,
    target_id: str,
    page: int = 1,
    page_size: int = 20,
    attachment_only: Optional[bool] = None,
) -> ServiceResult[PaginatedResult]:
    """List comments / attachment-only sends for a target.

    ``attachment_only=True`` filters to rows with NULL body — preserves
    the historic behaviour of GET /<entity>/{id}/attachments after
    doc 35 collapsed standalone attachments into the same table.
    """
    if not is_valid_target_kind(target_kind):
        return ServiceResult.fail(
            error=f"Invalid target_kind '{target_kind}'.",
            error_type="validation_error",
        )

    if not target_exists(db, target_kind, target_id):
        return ServiceResult.fail(
            error=f"Target {target_kind} '{target_id}' not found.",
            error_type="not_found",
        )

    offset = calculate_offset(page, page_size)
    repo = CommentRepository(db)
    comments, total = repo.list_by_target(
        target_kind, target_id,
        offset=offset, limit=page_size,
        attachment_only=attachment_only,
    )

    return ServiceResult.ok(PaginatedResult(
        items=comments, total=total, page=page, page_size=page_size,
    ))
