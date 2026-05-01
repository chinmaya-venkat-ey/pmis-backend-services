"""List standalone attachments under a target. Newest first."""
from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.attachment_repository import (
    AttachmentRepository,
)
from .....shared.pagination import PaginatedResult, calculate_offset
from .....shared.service_result import ServiceResult

from ...comments._target_helper import is_valid_target_kind, target_exists


def list_standalone_attachments(
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
    items, total = AttachmentRepository(db).list_standalone_by_target(
        target_kind, target_id, offset=offset, limit=page_size,
    )
    return ServiceResult.ok(PaginatedResult(
        items=items, total=total, page=page, page_size=page_size,
    ))
