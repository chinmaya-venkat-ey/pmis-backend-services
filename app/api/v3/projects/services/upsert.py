"""
Project upsert service.

Idempotent create-or-update by **id** (which is itself a UUID). Used by the
project creation wizard so that re-submitting Step 1 (e.g. after clicking
Back) updates the same row instead of creating duplicates.

Frontend generates a fresh UUID at wizard start (e.g. ``crypto.randomUUID()``)
and sends ``PUT /api/v3/projects/{uuid}`` on every Save & Next click. First
call -> INSERT with that id. Later calls -> UPDATE.
"""
from typing import Optional, Tuple
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.project_repository import ProjectRepository
from .....domain.projects.project import Project
from .....shared.service_result import ServiceResult
from .....shared.utils import normalize_string

from .transitions import (
    CATEGORY_OTHERS,
    OWNER_OTHERS,
    validate_owner_pair,
)


def _looks_like_uuid(s: str) -> bool:
    try:
        UUID(s)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def upsert_project(
    db: Session,
    id: str,
    name: str,
    current_user_login: Optional[str],
    is_admin: bool,
    description: Optional[str] = None,
    active: bool = True,
    public: bool = False,
    status_explanation: Optional[str] = None,
    parent_id: Optional[str] = None,
    status: str = "new",
    owner: Optional[str] = None,
    owner_other: Optional[str] = None,
    category: Optional[str] = None,
    category_other: Optional[str] = None,
    category_other_reason: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ServiceResult[Tuple[Project, bool]]:
    """Create or update a project by its id (UUID string)."""
    if not _looks_like_uuid(id):
        return ServiceResult.fail(
            error="Invalid UUID format in URL.",
            error_type="validation_error",
        )

    name = normalize_string(name)
    if not name or len(name) > 255:
        return ServiceResult.fail(
            error="Invalid name. Must be 1-255 characters.",
            error_type="validation_error",
        )
    if description and len(description) > 5000:
        return ServiceResult.fail(
            error="Description too long. Maximum 5000 characters.",
            error_type="validation_error",
        )
    if status_explanation and len(status_explanation) > 5000:
        return ServiceResult.fail(
            error="Status explanation too long. Maximum 5000 characters.",
            error_type="validation_error",
        )
    if start_date is not None and end_date is not None and end_date < start_date:
        return ServiceResult.fail(
            error="end_date cannot be before start_date",
            error_type="validation_error",
        )
    # Owner is required on upsert (treated like create — the wizard always
    # supplies one). 'others' requires a non-empty `ownerOther` follow-up.
    # Mints a new divisions row on success when applicable (see below).
    owner, owner_other, owner_err = validate_owner_pair(
        owner, owner_other, require_owner=True, db=db,
    )
    if owner_err:
        return ServiceResult.fail(error=owner_err, error_type="validation_error")

    # 'others' idiom — symmetric with the create-project service.
    if category == CATEGORY_OTHERS:
        co = normalize_string(category_other) if category_other else ""
        if not co:
            return ServiceResult.fail(
                error="categoryOther is required when category is 'others'.",
                error_type="validation_error",
            )
        if len(co) > 255:
            return ServiceResult.fail(
                error="categoryOther must be 1-255 characters.",
                error_type="validation_error",
            )
        category_other = co
        cor = normalize_string(category_other_reason) if category_other_reason else ""
        if not cor:
            return ServiceResult.fail(
                error="categoryOtherReason is required when category is 'others'.",
                error_type="validation_error",
            )
        if len(cor) > 1000:
            return ServiceResult.fail(
                error="categoryOtherReason must be 1-1000 characters.",
                error_type="validation_error",
            )
        category_other_reason = cor
    else:
        if category_other is not None and normalize_string(category_other) != "":
            return ServiceResult.fail(
                error="categoryOther may only be provided when category is 'others'.",
                error_type="validation_error",
            )
        category_other = None
        if category_other_reason is not None and normalize_string(category_other_reason) != "":
            return ServiceResult.fail(
                error="categoryOtherReason may only be provided when category is 'others'.",
                error_type="validation_error",
            )
        category_other_reason = None

    repository = ProjectRepository(db)

    # Ownership gate previously compared `existing.owner` against the
    # current user's login. With owner now being a division code, that
    # comparison can never match for non-admins. Route-level permission
    # (PROJECTS_CREATE) is the gate; we no longer second-guess it here.
    # `is_admin` and `current_user_login` are still accepted as args for
    # call-site stability but unused below.

    if parent_id is not None and not repository.exists_by_id(parent_id):
        return ServiceResult.fail(
            error=f"Parent project with ID {parent_id} does not exist",
            error_type="not_found",
        )

    try:
        project, created = repository.upsert_by_id(
            id=id,
            name=name,
            description=description,
            active=active,
            public=public,
            status_explanation=status_explanation,
            parent_id=parent_id,
            status=status,
            owner=owner,
            owner_other=owner_other,
            category=category,
            category_other=category_other,
            category_other_reason=category_other_reason,
            start_date=start_date,
            end_date=end_date,
        )
        # NOTE: pre-doc-20, this point used to upsert a divisions row from
        # the user's free-text ``owner_other`` label. That auto-create
        # path was removed across all three project-write entry points
        # (create / update / upsert) — see the matching notes in
        # services/create.py and services/update.py. The divisions catalog
        # is now strictly admin-managed via POST /api/v3/master/divisions/create.
        return ServiceResult.ok((project, created))
    except Exception as e:
        return ServiceResult.fail(
            error=f"Failed to upsert project: {str(e)}",
            error_type="internal_error",
        )
