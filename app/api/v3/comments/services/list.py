"""List-comments service. Newest first, paginated."""
from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.attachment_repository import (
    AttachmentRepository,
)
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
) -> ServiceResult[PaginatedResult]:
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
        target_kind, target_id, offset=offset, limit=page_size,
    )

    # Hydrate attachments per comment. N+1 in the simplest form; fine for
    # page sizes <=100 (and typical comments per page <=20). If profile
    # shows it as a hotspot later, batch-load with one IN query.
    att_repo = AttachmentRepository(db)
    for c in comments:
        c.attachments = att_repo.list_by_comment(c.id)

    return ServiceResult.ok(PaginatedResult(
        items=comments, total=total, page=page, page_size=page_size,
    ))
