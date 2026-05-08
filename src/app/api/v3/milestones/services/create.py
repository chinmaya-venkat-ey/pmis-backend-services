"""Create a milestone under a project."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_milestone_activity_writable
from .....domain.milestones.milestone import (
    MILESTONE_STATUS_CHOICES,
    MILESTONE_STATUS_DEFAULT,
    Milestone,
)
from .....infrastructure.db.models.milestone import MilestoneModel
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.milestone_repository import MilestoneRepository
from .....infrastructure.db.repositories.vendor_repository import VendorRepository
from .....shared.date_rules import validate_entity_dates
from .....shared.dep_date_rules import (
    collect_milestone_forward_violations,
    raise_milestone_forward_if_violations,
)
from .....shared.labels import (
    KIND_MILESTONE,
    build_label_index_for_project,
    normalize_dependency_inputs,
)
from ...projects.services.audit import ACTION_MILESTONE_CREATE, record_audit


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
    depends_on: Optional[List[str]] = None,
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
      - If ``depends_on`` given, every target id must reference a live
        milestone in the SAME project (cross-milestone within the project
        is the point of this feature). No self-edge is possible on create
        (the new id doesn't exist yet); cycle detection kicks in on update.
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
    # Doc 37 part 1: catalog-first; fallback to in-code tuple.
    from .....infrastructure.db.models.milestone_status import (
        MilestoneStatusModel,
    )
    from .....shared.static_catalog import active_codes, is_known_code
    if not is_known_code(
        db, resolved_status,
        model=MilestoneStatusModel,
        fallback=MILESTONE_STATUS_CHOICES,
    ):
        valid = sorted(active_codes(
            db, model=MilestoneStatusModel,
            fallback=MILESTONE_STATUS_CHOICES,
        ))
        raise ValidationError(
            f"Milestone status must be one of: {', '.join(valid)}."
        )

    # Validate depends_on targets BEFORE creating the row. Accepts UUIDs
    # or labels (e.g. "M2"); see app/shared/labels.py.
    desired_deps: List[str] = []
    if depends_on is not None:
        dep_repo = DependencyRepository(db)
        desired_deps = normalize_dependency_inputs(
            db,
            project_id=project_id,
            expected_kind=KIND_MILESTONE,
            raw_inputs=depends_on,
            existence_check=dep_repo.existing_target_milestone_ids,
        )

        # Doc 31: milestone-specific dep-date rules —
        #   source.start_date >= target.start_date  (equality OK)
        #   source.end_date   >  target.end_date    (strict)
        # Both must hold. See app/shared/dep_date_rules.py.
        if desired_deps:
            target_rows = (
                db.query(
                    MilestoneModel.id, MilestoneModel.name,
                    MilestoneModel.start_date, MilestoneModel.end_date,
                )
                .filter(MilestoneModel.id.in_(desired_deps))
                .all()
            )
            label_index = build_label_index_for_project(db, project_id)
            forward = [
                (label_index.label_of(KIND_MILESTONE, tid) or tname, tstart, tend)
                for (tid, tname, tstart, tend) in target_rows
            ]
            starts, ends = collect_milestone_forward_violations(
                source_start=start_date, source_end=end_date, targets=forward,
            )
            raise_milestone_forward_if_violations(
                starts, ends,
                source_label=f"Milestone '{name.strip()}'",
                source_start=start_date, source_end=end_date,
            )

    # Status-completion gate: if the caller wants to start the row off
    # as 'completed', every dep target must already be completed too.
    # Mirrors the PATCH-time gate in update_milestone.
    if resolved_status == "completed" and desired_deps:
        rows = (
            db.query(MilestoneModel.id, MilestoneModel.name, MilestoneModel.status)
            .filter(MilestoneModel.id.in_(desired_deps))
            .all()
        )
        blockers = [r for r in rows if (r[2] or "") != "completed"]
        if blockers:
            names = ", ".join(f"'{b[1]}'" for b in blockers[:3])
            more = "" if len(blockers) <= 3 else f" (+{len(blockers) - 3} more)"
            raise ValidationError(
                f"Cannot create this milestone as completed — the following "
                f"dependency target(s) are not yet completed: {names}{more}.",
            )

    vendor_repo = VendorRepository(db)
    resolved_vendor_ids: List[str] = []
    if vendor_ids:
        # Doc 25: each entry can be a UUID or a ``VN-...`` code. Resolve
        # to canonical UUIDs first, then run the existing
        # active + on-project checks against the resolved set.
        unique_input = list(dict.fromkeys(vendor_ids))
        resolved_pairs = [
            (token, vendor_repo.resolve_id(token)) for token in unique_input
        ]
        unresolved = [t for (t, rid) in resolved_pairs if rid is None]
        if unresolved:
            raise ValidationError(
                f"Unknown vendor(s): {', '.join(unresolved)}"
            )
        canonical_ids = [rid for (_t, rid) in resolved_pairs]
        active = set(vendor_repo.existing_active_ids(canonical_ids))
        missing_active = [
            t for (t, rid) in resolved_pairs if rid not in active
        ]
        if missing_active:
            raise ValidationError(
                f"Unknown or inactive vendor(s): {', '.join(missing_active)}"
            )
        project_vendor_ids = set(vendor_repo.project_vendor_ids(project_id))
        not_on_project_tokens = [
            t for (t, rid) in resolved_pairs if rid not in project_vendor_ids
        ]
        if not_on_project_tokens:
            raise ValidationError(
                f"Vendor(s) not attached to this project: {', '.join(not_on_project_tokens)}. "
                "Add them to the project first."
            )
        resolved_vendor_ids = canonical_ids

    repo = MilestoneRepository(db)
    # Doc 30 follow-up: auto-bump on position collision.
    #
    # Pre-fix, the service only auto-assigned when ``position is None``.
    # If the caller supplied a position that was already taken by a live
    # milestone in the same project, the INSERT below tripped the
    # ``uq_milestones_project_position_live`` unique index and bubbled up
    # as a 500. Swagger UI's multipart "Try it out" auto-fills the
    # ``position`` field with ``0``, making the second milestone created
    # via Swagger a guaranteed crash.
    #
    # Position is only an ordering hint; if a caller's preferred slot is
    # already filled we silently fall back to the next free slot rather
    # than reject. Genuine "insert at the top" semantics aren't a thing
    # on this endpoint — repositioning happens via separate
    # update / move endpoints.
    if position is None or repo.position_taken(project_id, position):
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
    )

    if desired_deps:
        DependencyRepository(db).set_milestone_dependencies(
            m.id, project_id, desired_deps, actor_id=current_user_id,
        )
        db.commit()
        m.depends_on = list(desired_deps)

    if resolved_vendor_ids:
        vendor_repo.set_milestone_vendors(m.id, resolved_vendor_ids)
        db.commit()
        m.vendors = vendor_repo.list_milestone_vendors(m.id)

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
            "depends_on": desired_deps,
        },
    )
    db.commit()
    return m
