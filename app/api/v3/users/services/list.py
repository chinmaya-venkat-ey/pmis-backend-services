"""User listing service — ported from the monolith."""
from typing import Optional

from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.pagination import PaginatedResult, calculate_offset
from .....shared.service_result import ServiceResult


def list_users(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    is_admin: bool = False,
) -> ServiceResult[PaginatedResult]:
    if page < 1:
        return ServiceResult.fail(
            error="Page number must be >= 1", error_type="validation_error",
        )
    if page_size < 1 or page_size > 100:
        return ServiceResult.fail(
            error="Page size must be between 1 and 100",
            error_type="validation_error",
        )

    if not is_admin and status is None:
        status = "active"
    elif not is_admin and status != "active":
        return ServiceResult.fail(
            error="Only admin users can filter by non-active status",
            error_type="authorization_error",
        )

    offset = calculate_offset(page, page_size)
    repo = UserRepository(db)

    try:
        users, total = repo.list(offset=offset, limit=page_size, status=status)
        return ServiceResult.ok(
            PaginatedResult(items=users, total=total, page=page, page_size=page_size),
        )
    except Exception as e:
        return ServiceResult.fail(
            error=f"Failed to list users: {e}", error_type="internal_error",
        )
