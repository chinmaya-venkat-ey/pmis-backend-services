"""
Project update service.
"""
from typing import Any, Dict, List, Optional
from datetime import datetime

from sqlalchemy.orm import Session

from .....core.errors import AuthorizationError, DomainError, NotFoundError, ValidationError
from .....core.project_lock import assert_project_editable
from .....domain.projects.project import Project
from .....infrastructure.db.repositories.project_repository import ProjectRepository
from .....infrastructure.db.repositories.vendor_repository import VendorRepository
from .....shared.datetime import ensure_aware_utc
from .....shared.service_result import ServiceResult
from .....shared.utils import normalize_string

from .audit import ACTION_UPDATE, project_snapshot, record_audit
from .transitions import (
    CATEGORY_OTHERS,
    OWNER_OTHERS,
    PROJECT_CATEGORY_CHOICES,
    editable_fields_for,
    validate_owner_pair,
)


def normalize_string_or_none(s):
    """Strip + lowercase a string for comparison; return None on empty / None."""
    if s is None:
        return None
    s = s.strip()
    return s.lower() if s else None


def update_project(
    db: Session,
    project_id: str,
    *,
    actor_id: Optional[str],
    patch: Dict[str, Any],
    vendor_ids: Optional[List[str]] = None,
) -> ServiceResult[Project]:
    """
    Apply a field patch to a project.

    ``patch`` is a dict of snake_case field names (the controller translates
    from the request schema). Fields outside the editable whitelist for the
    project's current state are rejected with 422 invalid_field.

    ``vendor_ids`` is independent of the column whitelist because vendors
    live in an association table. Semantics:
      - None  : leave the project's current vendor list unchanged.
      - []    : clear the vendor list.
      - [...] : replace the vendor list with exactly these UUIDs (must all
                reference existing active vendors; otherwise 422).
    """
    repo = ProjectRepository(db)
    project = repo.get_by_id(project_id)
    if project is None:
        return ServiceResult.fail(
            error=f"Project with ID {project_id} not found",
            error_type="not_found",
        )

    # Lock: published baselines (and, once M/A/T/S contributor extends this,
    # their subtrees) are not editable. Upstream's assert_project_editable
    # raises NotFoundError for soft-deleted / missing rows and
    # AuthorizationError for a published baseline.
    try:
        assert_project_editable(db, project_id)
    except NotFoundError as e:
        return ServiceResult.fail(error=e.message, error_type="not_found")
    except AuthorizationError as e:
        return ServiceResult.fail(
            error=e.message,
            error_type="project_locked",
            details={"errorIdentifier": "project_locked"},
        )
    except DomainError as e:
        return ServiceResult.fail(error=e.message, error_type="validation_error")

    # Drop keys whose value is None — None means "unchanged" in a PATCH.
    supplied = {k: v for k, v in patch.items() if v is not None}

    allowed = editable_fields_for(project)
    rejected = sorted(set(supplied) - allowed)
    if rejected:
        return ServiceResult.fail(
            error=(
                f"Fields not editable in current project state: "
                f"{', '.join(rejected)}"
            ),
            error_type="invalid_field",
            details={
                "errorIdentifier": "invalid_field",
                "rejected": rejected,
                "allowed": sorted(allowed),
                "project_status": project.status,
            },
        )

    if "name" in supplied:
        supplied["name"] = normalize_string(supplied["name"])
        if not supplied["name"] or len(supplied["name"]) > 255:
            return ServiceResult.fail(
                error="Invalid name. Must be 1-255 characters.",
                error_type="validation_error",
            )

    if "description" in supplied and supplied["description"] is not None:
        if len(supplied["description"]) > 5000:
            return ServiceResult.fail(
                error="Description too long. Maximum 5000 characters.",
                error_type="validation_error",
            )

    if "status_explanation" in supplied and supplied["status_explanation"] is not None:
        if len(supplied["status_explanation"]) > 5000:
            return ServiceResult.fail(
                error="Status explanation too long. Maximum 5000 characters.",
                error_type="validation_error",
            )

    # "Must be in the future" is enforced by the Pydantic schema for the
    # supplied fields; skip the duplicate check to avoid naive/aware clashes.
    effective_start = ensure_aware_utc(
        supplied.get("start_date", project.start_date)
    )
    effective_end = ensure_aware_utc(
        supplied.get("end_date", project.end_date)
    )
    if (
        effective_start is not None
        and effective_end is not None
        and effective_end < effective_start
    ):
        return ServiceResult.fail(
            error="end_date cannot be before start_date",
            error_type="validation_error",
        )

    # Owner / ownerOther on PATCH. Effective values (patch ∪ existing row)
    # are run through the shared validator so the 'others' idiom is
    # enforced consistently with create / upsert.
    if "owner" in supplied or "owner_other" in supplied:
        eff_owner = supplied.get("owner", project.owner)
        # If the caller is moving owner AWAY from 'others' without
        # explicitly touching owner_other, the existing owner_other on
        # the row becomes vestigial — don't fail the cross-check on
        # stale data. (Cleanup of the stale column itself needs a repo
        # extension; same TODO as categoryOther.)
        if "owner_other" in supplied:
            eff_owner_other = supplied["owner_other"]
        elif normalize_string_or_none(eff_owner) == OWNER_OTHERS:
            eff_owner_other = project.owner_other
        else:
            eff_owner_other = None
        # On PATCH, owner is "not required" only when the field is absent
        # from the supplied dict. If the caller sent a key for owner, we
        # require it to resolve to a value (require_owner=True).
        norm_owner, norm_owner_other, owner_err = validate_owner_pair(
            eff_owner, eff_owner_other,
            require_owner=("owner" in supplied),
            db=db,
        )
        if owner_err:
            return ServiceResult.fail(
                error=owner_err, error_type="validation_error",
            )
        if "owner" in supplied:
            if norm_owner is None:
                del supplied["owner"]
            else:
                supplied["owner"] = norm_owner
        if "owner_other" in supplied:
            if norm_owner_other is None:
                # Repo treats None as "leave unchanged"; same TODO as
                # categoryOther below.
                del supplied["owner_other"]
            else:
                supplied["owner_other"] = norm_owner_other

    # Category 'others' idiom — symmetric with create_project / upsert_project.
    # Effective values combine the patch with the existing row so a partial
    # PATCH (e.g. only categoryOtherReason) doesn't false-trigger the rules.
    if "category" in supplied or "category_other" in supplied or "category_other_reason" in supplied:
        eff_category = supplied.get("category", project.category)
        eff_other = supplied.get("category_other", project.category_other)
        eff_reason = supplied.get("category_other_reason", project.category_other_reason)

        # Doc 37 part 1: catalog-first; fallback to in-code tuple.
        if eff_category is not None:
            from .....infrastructure.db.models.project_category import (
                ProjectCategoryModel,
            )
            from .....shared.static_catalog import is_known_code
            if not is_known_code(
                db, eff_category,
                model=ProjectCategoryModel,
                fallback=PROJECT_CATEGORY_CHOICES,
            ):
                return ServiceResult.fail(
                    error=f"Invalid category '{eff_category}'.",
                    error_type="validation_error",
                )

        if eff_category == CATEGORY_OTHERS:
            normalised_other = normalize_string(eff_other) if eff_other else ""
            if not normalised_other:
                return ServiceResult.fail(
                    error="categoryOther is required when category is 'others'.",
                    error_type="validation_error",
                )
            if len(normalised_other) > 255:
                return ServiceResult.fail(
                    error="categoryOther must be 1-255 characters.",
                    error_type="validation_error",
                )
            normalised_reason = normalize_string(eff_reason) if eff_reason else ""
            if not normalised_reason:
                return ServiceResult.fail(
                    error="categoryOtherReason is required when category is 'others'.",
                    error_type="validation_error",
                )
            if len(normalised_reason) > 1000:
                return ServiceResult.fail(
                    error="categoryOtherReason must be 1-1000 characters.",
                    error_type="validation_error",
                )
            if "category_other" in supplied:
                supplied["category_other"] = normalised_other
            if "category_other_reason" in supplied:
                supplied["category_other_reason"] = normalised_reason
        else:
            # Non-'others' category MUST NOT carry these fields. Reject
            # them with a clear error rather than silently dropping the
            # supplied value (the repo's None-skip semantics would prevent
            # the caller from clearing them via a PATCH anyway). FE must
            # null them out explicitly via a follow-up administrative
            # operation if they were previously set — see the TODO below.
            if (
                "category_other" in supplied
                and supplied["category_other"] is not None
                and normalize_string(supplied["category_other"]) != ""
            ):
                return ServiceResult.fail(
                    error="categoryOther may only be provided when category is 'others'.",
                    error_type="validation_error",
                )
            if (
                "category_other_reason" in supplied
                and supplied["category_other_reason"] is not None
                and normalize_string(supplied["category_other_reason"]) != ""
            ):
                return ServiceResult.fail(
                    error="categoryOtherReason may only be provided when category is 'others'.",
                    error_type="validation_error",
                )
            # TODO: when switching away from 'others' the previously-stored
            # category_other / category_other_reason rows are left in place.
            # Repo.update treats None as "leave unchanged" so we can't clear
            # them here; needs a small repo extension (sentinel for explicit
            # null) to fix cleanly. Low priority — affects display only,
            # never validation.

    # Vendor-list replacement. Handled outside the column whitelist.
    # Doc 25: each entry can be a UUID or a ``VN-...`` code; resolve
    # before validating so callers can use either form.
    vendor_repo = VendorRepository(db)
    will_replace_vendors = vendor_ids is not None
    clean_vendor_ids: List[str] = []
    if will_replace_vendors:
        unique_input = list(dict.fromkeys(vendor_ids or []))
        if unique_input:
            resolved_pairs = [
                (token, vendor_repo.resolve_id(token)) for token in unique_input
            ]
            unresolved = [t for (t, rid) in resolved_pairs if rid is None]
            if unresolved:
                return ServiceResult.fail(
                    error=f"Unknown vendor(s): {', '.join(unresolved)}",
                    error_type="validation_error",
                )
            canonical_ids = [rid for (_t, rid) in resolved_pairs]
            ok_ids = set(vendor_repo.existing_active_ids(canonical_ids))
            missing_tokens = [
                t for (t, rid) in resolved_pairs if rid not in ok_ids
            ]
            if missing_tokens:
                return ServiceResult.fail(
                    error=f"Unknown or inactive vendor(s): {', '.join(missing_tokens)}",
                    error_type="validation_error",
                )
            clean_vendor_ids = canonical_ids

    before = project_snapshot(project)

    try:
        updated = repo.update(
            project_id=project_id,
            updated_by=actor_id,
            **supplied,
        )
        if updated is None:
            return ServiceResult.fail(
                error=f"Project with ID {project_id} not found",
                error_type="not_found",
            )

        if will_replace_vendors:
            vendor_repo.set_project_vendors(project_id, clean_vendor_ids)
            updated.vendors = vendor_repo.list_project_vendors(project_id)

        # NOTE: pre-doc-20, this point used to upsert a divisions row from
        # the patched ``owner_other`` label. That auto-create path was
        # removed — see the matching note in services/create.py. The
        # divisions catalog is now strictly admin-managed via
        # POST /api/v3/master/divisions/create.

        record_audit(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action=ACTION_UPDATE,
            before=before,
            after=project_snapshot(updated),
        )

        db.commit()
        return ServiceResult.ok(updated)

    except Exception as e:
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to update project: {str(e)}",
            error_type="internal_error",
        )
