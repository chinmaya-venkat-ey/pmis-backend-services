"""
Create a new version of a published baseline project.

Transactional:
  1. Validate source is a published baseline and has no active version.
  2. Insert clone row (is_version=true, version_of=source.id, status='new',
     fresh uuid + fresh project_code).
  3. Deep-clone the M/A/T/S subtree via the milestones contributor's hook.
  4. Commit.
"""
from typing import Optional

from sqlalchemy.orm import Session

from .....api.v3.milestones.services.clone import clone_tree_for_version
from .....domain.projects.project import Project
from .....infrastructure.db.repositories.project_repository import ProjectRepository
from .....shared.service_result import ServiceResult

from .audit import ACTION_VERSION_CREATE, project_snapshot, record_audit
from .transitions import STATUS_NEW, STATUS_PUBLISHED


def create_version(
    db: Session,
    source_id: str,
    *,
    actor_id: Optional[int],
) -> ServiceResult[Project]:
    repo = ProjectRepository(db)
    source = repo.get_by_id(source_id)
    if source is None:
        return ServiceResult.fail(
            error="Source project not found.",
            error_type="not_found",
        )

    if source.is_version:
        return ServiceResult.fail(
            error="Cannot create a version from a version. Version the original baseline instead.",
            error_type="invalid_source",
            details={"errorIdentifier": "invalid_source", "source_is_version": True},
        )

    if (source.status or "").lower() != STATUS_PUBLISHED:
        return ServiceResult.fail(
            error="Versions can only be created from a published baseline.",
            error_type="invalid_source",
            details={
                "errorIdentifier": "invalid_source",
                "source_status": source.status,
                "required_status": STATUS_PUBLISHED,
            },
        )

    if repo.active_version_exists(source.id):
        return ServiceResult.fail(
            error=(
                "An active version already exists for this baseline. "
                "Suspend the existing active version before creating a new one."
            ),
            error_type="active_version_exists",
            details={
                "errorIdentifier": "active_version_exists",
                "baseline_id": source.id,
            },
        )

    version_no = repo.next_version_no(source.id)

    try:
        # The version row gets its own fresh uuid + project_code — generated
        # by the repository (no inputs needed). Data fields cloned from source.
        target = repo.create(
            name=source.name,
            description=source.description,
            active=source.active,
            public=source.public,
            status_explanation=None,
            parent_id=source.parent_id,
            status=STATUS_NEW,
            owner=source.owner,
            category=source.category,
            category_other=getattr(source, "category_other", None),
            category_other_reason=getattr(source, "category_other_reason", None),
            start_date=source.start_date,
            end_date=source.end_date,
            actual_start_date=None,
            actual_end_date=None,
            is_version=True,
            version_of=source.id,
            baseline_id=source.id,
            version_no=version_no,
            created_by=actor_id,
        )

        # Carry the source project's vendor list onto the version.
        from .....infrastructure.db.repositories.vendor_repository import (
            VendorRepository,
        )
        vendor_repo = VendorRepository(db)
        src_vendor_ids = vendor_repo.project_vendor_ids(source.id)
        if src_vendor_ids:
            vendor_repo.set_project_vendors(target.id, src_vendor_ids)
            target.vendors = vendor_repo.list_project_vendors(target.id)

        # Hook: deep-clone the M/A/T/S subtree into the new version row.
        clone_tree_for_version(
            db,
            source_project_id=source.id,
            target_project_id=target.id,
            created_by=actor_id,
        )

        record_audit(
            db,
            project_id=target.id,
            actor_id=actor_id,
            action=ACTION_VERSION_CREATE,
            before=None,
            after={
                **project_snapshot(target),
                "source_project_id": source.id,
                "source_id": source.id,
                "source_project_code": source.project_code,
            },
        )

        db.commit()
        return ServiceResult.ok(target)

    except Exception as e:
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to create version: {str(e)}",
            error_type="internal_error",
        )
