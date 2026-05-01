"""Create a milestone under a project."""
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_milestone_activity_writable
from .....domain.milestones.milestone import (
    MILESTONE_STATUS_CHOICES,
    MILESTONE_STATUS_DEFAULT,
    Milestone,
)
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.repositories.milestone_repository import MilestoneRepository
from .....infrastructure.db.repositories.vendor_repository import VendorRepository
from .....shared.date_rules import validate_entity_dates
from ...projects.services.audit import record_audit
from ...projects.services.baseline_version_sync import (
    ACTION_MILESTONE_CREATE,
    propagate_milestone_create,
)


def create_milestone(
    db: Session,
    *,
    project_id: str,
    name: str,
    description: Optional[str],
    start_date: datetime,
    end_date: datetime,
    position: Optional[int],
    current_user_id: Optional[int],
    status: Optional[str] = None,
    depends: Optional[List[Any]] = None,
    vendor_ids: Optional[List[str]] = None,
) -> Milestone:
    """
    Create a milestone under the given project.

    Validation:
      - Project must exist, not deleted, not a published baseline.
      - Project must have a start_date set (we need it for date rules).
      - start_date >= project.start_date; end_date >= start_date.
      - If ``vendor_ids`` given, each must also appear in the project's vendors.
      - ``status`` must be in MILESTONE_STATUS_CHOICES (default 'not_completed').
    """
    assert_milestone_activity_writable(db, project_id)

    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if project is None:
        raise NotFoundError("The project could not be found.")
    if project.start_date is None:
        raise ValidationError(
            "The project does not have a start date yet. "
            "Please set the project start date before adding milestones."
        )

    # Parent of a milestone is the project itself.
    validate_entity_dates(
        entity_start=start_date,
        entity_end=end_date,
        actual_start=None,
        actual_end=None,
        parent_start_date=project.start_date,
        project_start_date=project.start_date,
        entity_label="milestone",
        parent_label="project",
    )

    resolved_status = status or MILESTONE_STATUS_DEFAULT
    if resolved_status not in MILESTONE_STATUS_CHOICES:
        raise ValidationError(
            f"Milestone status must be one of: {', '.join(MILESTONE_STATUS_CHOICES)}."
        )

    # Vendor validation: each must exist/be active AND be attached to the
    # parent project. We don't allow attaching vendors to a milestone that the
    # project hasn't signed off on.
    vendor_repo = VendorRepository(db)
    resolved_vendor_ids: List[str] = []
    if vendor_ids:
        unique = list(dict.fromkeys(vendor_ids))
        active = set(vendor_repo.existing_active_ids(unique))
        missing_active = [v for v in unique if v not in active]
        if missing_active:
            raise ValidationError(
                f"Unknown or inactive vendor(s): {', '.join(missing_active)}"
            )
        project_vendor_ids = set(vendor_repo.project_vendor_ids(project_id))
        not_on_project = [v for v in unique if v not in project_vendor_ids]
        if not_on_project:
            raise ValidationError(
                f"Vendor(s) not attached to this project: {', '.join(not_on_project)}. "
                "Add them to the project first."
            )
        resolved_vendor_ids = unique

    repo = MilestoneRepository(db)
    if position is None:
        position = repo.next_position(project_id)

    m = repo.create(
        project_id=project_id,
        name=name.strip(),
        description=description,
        start_date=start_date,
        end_date=end_date,
        position=position,
        created_by=current_user_id,
        status=resolved_status,
        depends=depends,
    )

    if resolved_vendor_ids:
        vendor_repo.set_milestone_vendors(m.id, resolved_vendor_ids)
        db.commit()
        m.vendors = vendor_repo.list_milestone_vendors(m.id)

    # Audit the baseline create and fan out to active versions.
    record_audit(
        db,
        project_id=project_id,
        actor_id=current_user_id,
        action=ACTION_MILESTONE_CREATE,
        before=None,
        after={
            "milestone_id": m.id,
            "name": m.name,
            "start_date": m.start_date.isoformat() if m.start_date else None,
            "end_date": m.end_date.isoformat() if m.end_date else None,
            "position": m.position,
            "status": resolved_status,
        },
    )
    db.commit()
    propagate_milestone_create(db, baseline_milestone_id=m.id, actor_id=current_user_id)

    return m
