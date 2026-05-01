"""User update + password update services.

Adds two important behaviours on top of the basic patch:
  - Setting ``status='active'`` on a currently soft-deleted user
    triggers a restore (clears ``deleted_at`` / ``deleted_by``).
  - Vendor and division updates are validated the same way as create
    (vendor exists; division enum; division_other only when 'others').
"""
from typing import Optional

from sqlalchemy.orm import Session

from .....core.security import hash_password
from .....domain.users.division import DIVISION_CHOICES, DIVISION_OTHERS
from .....domain.users.user import User
from .....infrastructure.db.models.vendor import VendorModel
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult
from .....shared.utils import (
    is_valid_email,
    is_valid_password,
    normalize_email,
    normalize_string,
)


_USER_STATUS_CHOICES = ("active", "inactive", "locked", "registered")


def update_user(
    db: Session,
    user_id: int,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    admin: Optional[bool] = None,
    status: Optional[str] = None,
    vendor_id: Optional[str] = None,
    division: Optional[str] = None,
    division_other: Optional[str] = None,
    requesting_user_id: Optional[int] = None,
    is_admin: bool = False,
) -> ServiceResult[User]:
    """Update a user's mutable fields."""
    repository = UserRepository(db)

    # Allow updating soft-deleted users (restore path); fetch with
    # include_deleted so we can detect the deleted state.
    user = repository.get_by_id(user_id, include_deleted=True)
    if not user:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found",
            error_type="not_found",
        )

    is_self = requesting_user_id == user_id

    # Authz checks ---------------------------------------------
    if admin is not None and not is_admin:
        return ServiceResult.fail(
            error="Only admin users can modify admin flag",
            error_type="authorization_error",
        )
    if status is not None and not is_admin:
        return ServiceResult.fail(
            error="Only admin users can modify user status",
            error_type="authorization_error",
        )
    if not is_admin and not is_self:
        return ServiceResult.fail(
            error="You can only update your own profile",
            error_type="authorization_error",
        )

    # Admin-protection guards ---------------------------------
    # These complement the delete-service guards so the API surface
    # cannot lock the system out of itself via demotion / deactivation.

    # Guard 1: An admin cannot demote themselves from admin.
    if admin is False and is_self and user.admin:
        return ServiceResult.fail(
            error="Cannot demote yourself from admin.",
            error_type="authorization_error",
        )

    # Guard 2 + 3: Last-active-admin protection on demotion + deactivation.
    if user.admin and not user.is_deleted():
        removing_admin_flag = admin is False
        deactivating_status = status == "inactive"
        if removing_admin_flag or deactivating_status:
            if not repository.has_other_active_admin(exclude_user_id=user_id):
                action = "demote" if removing_admin_flag else "deactivate"
                return ServiceResult.fail(
                    error=(
                        f"Cannot {action} the last active admin. "
                        "Promote another user to admin first."
                    ),
                    error_type="validation_error",
                )

    # Field validation -----------------------------------------
    if email is not None:
        email = normalize_email(email)
        if not is_valid_email(email):
            return ServiceResult.fail(
                error="Invalid email format",
                error_type="validation_error",
            )
        existing = repository.get_by_email(email, include_deleted=True)
        if existing and existing.id != user_id:
            return ServiceResult.fail(
                error=f"Email '{email}' is already in use",
                error_type="already_exists",
            )

    if status is not None and status not in _USER_STATUS_CHOICES:
        return ServiceResult.fail(
            error=(
                f"Invalid status. Must be one of: "
                f"{', '.join(_USER_STATUS_CHOICES)}"
            ),
            error_type="validation_error",
        )

    if vendor_id is not None:
        vendor = (
            db.query(VendorModel)
            .filter(VendorModel.id == vendor_id)
            .filter(VendorModel.deleted_at.is_(None))
            .first()
        )
        if vendor is None:
            return ServiceResult.fail(
                error=f"Vendor '{vendor_id}' not found or deleted.",
                error_type="validation_error",
                details={"field": "vendorId", "value": vendor_id},
            )

    # Division: needs joint validation with division_other (and the
    # already-stored value, since the patch may change one without the
    # other).
    final_division = division if division is not None else user.division
    final_division_other_input = (
        normalize_string(division_other)
        if division_other is not None else user.division_other
    )
    clear_division_other = False

    if division is not None:
        if final_division not in DIVISION_CHOICES:
            return ServiceResult.fail(
                error=(
                    f"Division must be one of: {', '.join(DIVISION_CHOICES)}."
                ),
                error_type="validation_error",
            )
        if final_division != DIVISION_OTHERS and division_other is None:
            # Division is changing AWAY from 'others' and the caller
            # didn't supply a new label → clear the existing one.
            clear_division_other = True

    if division_other is not None:
        if final_division == DIVISION_OTHERS and not final_division_other_input:
            return ServiceResult.fail(
                error="divisionOther is required when division is 'others'.",
                error_type="validation_error",
            )
        if final_division != DIVISION_OTHERS and final_division_other_input:
            return ServiceResult.fail(
                error=(
                    "divisionOther may only be provided when division is "
                    "'others'."
                ),
                error_type="validation_error",
            )

    # Restore detection: admin setting status=active on a deleted user.
    restore = bool(
        is_admin
        and status == "active"
        and user.is_deleted()
    )

    # Execute --------------------------------------------------
    try:
        updated = repository.update(
            user_id=user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            admin=admin,
            status=status,
            vendor_id=vendor_id,
            division=division,
            division_other=division_other,
            clear_division_other=clear_division_other,
            restore=restore,
        )
        if not updated:
            return ServiceResult.fail(
                error=f"Failed to update user with ID {user_id}",
                error_type="internal_error",
            )
        db.commit()
        return ServiceResult.ok(updated)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to update user: {e}",
            error_type="internal_error",
        )


def update_password(
    db: Session,
    user_id: int,
    new_password: str,
    requesting_user_id: Optional[int] = None,
    is_admin: bool = False,
) -> ServiceResult[bool]:
    """Update a user's password. Self or admin only."""
    repository = UserRepository(db)
    user = repository.get_by_id(user_id)
    if not user:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found",
            error_type="not_found",
        )

    is_self = requesting_user_id == user_id
    if not is_admin and not is_self:
        return ServiceResult.fail(
            error="You can only update your own password",
            error_type="authorization_error",
        )

    if not is_valid_password(new_password):
        return ServiceResult.fail(
            error="Password must be at least 8 characters long",
            error_type="validation_error",
        )

    try:
        if not repository.update_password(user_id, hash_password(new_password)):
            return ServiceResult.fail(
                error=f"Failed to update password for user with ID {user_id}",
                error_type="internal_error",
            )
        db.commit()
        return ServiceResult.ok(True)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to update password: {e}",
            error_type="internal_error",
        )
