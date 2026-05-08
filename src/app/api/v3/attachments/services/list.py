"""List standalone attachments (doc 35: comments with NULL body).

After doc 35 there's no separate attachments table. The FE still wants
a "files only" view of the panel, so this service filters comments to
rows with body = NULL (the marker for the attachment-only path).
"""
from sqlalchemy.orm import Session

from .....shared.pagination import PaginatedResult
from .....shared.service_result import ServiceResult

from ...comments.services import list_comments


def list_standalone_attachments(
    db: Session,
    *,
    target_kind: str,
    target_id: str,
    page: int = 1,
    page_size: int = 20,
) -> ServiceResult[PaginatedResult]:
    """Filter the unified comments table down to attachment-only rows."""
    return list_comments(
        db=db,
        target_kind=target_kind,
        target_id=target_id,
        page=page,
        page_size=page_size,
        attachment_only=True,
    )
