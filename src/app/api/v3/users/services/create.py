"""
User creation service.

Single transaction:
  1. Validate inputs (login, email, password, division enum, division_other
     when division == 'others').
  2. Verify the supplied vendor exists and is not soft-deleted.
  3. Verify each project_id references an existing non-deleted project.
  4. Insert the user row + project_members rows.
  5. Commit.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from .....core.security import hash_password
from .....domain.resource_types.resource_type import (
    DIVISION_CHOICES,
    DIVISION_OTHERS,
)
from .....domain.users.user import User
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.project_member import ProjectMemberModel
from .....infrastructure.db.models.vendor import VendorModel
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....infrastructure.db.repositories.vendor_repository import VendorRepository
from .....shared.service_result import ServiceResult
from .....shared.utils import (
    is_valid_email,
    is_valid_login,
    is_valid_password,
    normalize_email,
    normalize_login,
    normalize_string,
)


def create_user(
    db: Session,
    login: str,
    email: str,
    password: str,
    *,
    vendor_id: str,
    division: str,
    phone_number: str,
    division_other: Optional[str] = None,
    project_ids: Optional[List[str]] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    admin: bool = False,
) -> ServiceResult[User]:
    """
    Create a new user and its project mappings.

    All required-field semantics are enforced here so callers (the API
    controller) don't have to repeat them.
    """
    # ---- Normalize ------------------------------------------------------
    login = normalize_login(login)
    email = normalize_email(email)
    division = (division or "").strip().lower()
    division_other = (
        normalize_string(division_other) if division_other is not None else None
    )

    # ---- Format validation ----------------------------------------------
    if not is_valid_login(login):
        return ServiceResult.fail(
            error="Invalid login format. Must be 3-50 alphanumeric characters, underscores, or hyphens.",
            error_type="validation_error",
        )
    if not is_valid_email(email):
        return ServiceResult.fail(
            error="Invalid email format",
            error_type="validation_error",
        )
    if not is_valid_password(password):
        return ServiceResult.fail(
            error="Password must be at least 8 characters long",
            error_type="validation_error",
        )

    # ---- Division ------------------------------------------------------
    if division not in DIVISION_CHOICES:
        return ServiceResult.fail(
            error=f"Division must be one of: {', '.join(DIVISION_CHOICES)}.",
            error_type="validation_error",
        )
    if division == DIVISION_OTHERS:
        if not division_other:
            return ServiceResult.fail(
                error="divisionOther is required when division is 'others'.",
                error_type="validation_error",
            )
    else:
        if division_other:
            return ServiceResult.fail(
                error="divisionOther may only be provided when division is 'others'.",
                error_type="validation_error",
            )
        division_other = None

    # ---- Phone number (required) ---------------------------------------
    # Schema already enforces non-empty + max 50; this guard catches the
    # direct-service-call path (CLI / internal scripts) that bypasses the
    # Pydantic layer. Mirrors the vendor_id guard below.
    phone_number = (phone_number or "").strip()
    if not phone_number:
        return ServiceResult.fail(
            error="phoneNumber is required.",
            error_type="validation_error",
        )
    if len(phone_number) > 50:
        return ServiceResult.fail(
            error="phoneNumber must be 1-50 characters.",
            error_type="validation_error",
        )

    # ---- Vendor --------------------------------------------------------
    # Doc 25: ``vendor_id`` accepts either a UUID or a ``VN-...`` code.
    # We resolve to the canonical UUID first (None on unresolvable),
    # then verify the underlying row exists and is live.
    if not vendor_id:
        return ServiceResult.fail(
            error="vendorId is required.",
            error_type="validation_error",
        )
    canonical_vendor_id = VendorRepository(db).resolve_id(vendor_id)
    vendor = None
    if canonical_vendor_id:
        vendor = (
            db.query(VendorModel)
            .filter(VendorModel.id == canonical_vendor_id)
            .filter(VendorModel.deleted_at.is_(None))
            .first()
        )
    if vendor is None:
        return ServiceResult.fail(
            error=f"Vendor '{vendor_id}' not found or has been deleted.",
            error_type="validation_error",
            details={"field": "vendorId", "value": vendor_id},
        )
    # Pin to the canonical UUID so the inserted row holds the immutable
    # FK regardless of whether the caller sent a UUID or a code.
    vendor_id = canonical_vendor_id

    # ---- Project mapping ------------------------------------------------
    project_ids = list(dict.fromkeys(project_ids or []))  # de-dupe, preserve order
    if not project_ids:
        return ServiceResult.fail(
            error="At least one project mapping is required (project_ids).",
            error_type="validation_error",
        )
    found_ids = {
        pid
        for (pid,) in db.query(ProjectModel.id)
        .filter(ProjectModel.id.in_(project_ids))
        .filter(ProjectModel.deleted_at.is_(None))
        .all()
    }
    missing = [p for p in project_ids if p not in found_ids]
    if missing:
        return ServiceResult.fail(
            error=f"Project(s) not found or deleted: {', '.join(missing)}",
            error_type="validation_error",
            details={"field": "projectIds", "missing": missing},
        )

    # ---- Uniqueness checks ---------------------------------------------
    repository = UserRepository(db)
    if repository.exists_by_login(login):
        return ServiceResult.fail(
            error=f"User with login '{login}' already exists",
            error_type="already_exists",
        )
    if repository.exists_by_email(email):
        return ServiceResult.fail(
            error=f"User with email '{email}' already exists",
            error_type="already_exists",
        )

    # ---- Persist --------------------------------------------------------
    try:
        user = repository.create(
            login=login,
            email=email,
            hashed_password=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            admin=admin,
            vendor_id=vendor_id,
            division=division,
            division_other=division_other,
            phone_number=phone_number,
        )

        # Wire up project_members rows.
        for pid in project_ids:
            db.add(ProjectMemberModel(
                project_id=pid,
                user_id=user.id,
                roles=[],   # role per project — future feature
            ))
        db.flush()

        # Hydrate the response with the just-mapped projects.
        # Re-fetch via repo so the projects array reflects the live DB
        # (filters closed/soft-deleted).
        hydrated = repository.get_by_id(user.id)
        db.commit()
        return ServiceResult.ok(hydrated or user)

    except Exception as e:  # noqa: BLE001
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to create user: {e}",
            error_type="internal_error",
        )
