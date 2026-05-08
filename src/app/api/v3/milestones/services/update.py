"""Update a milestone (partial; with date re-validation)."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_milestone_activity_writable
from .....domain.milestones.milestone import (
    MILESTONE_STATUS_CHOICES,
    MILESTONE_STATUS_COMPLETED,
    Milestone,
)
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.models.milestone import MilestoneModel
from .....infrastructure.db.models.milestone_dependency import (
    MilestoneDependencyModel,
)
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.milestone_repository import MilestoneRepository
from .....infrastructure.db.repositories.vendor_repository import VendorRepository
from .....shared.date_rules import validate_entity_dates
from .....shared.dep_date_rules import (
    collect_milestone_forward_violations,
    collect_milestone_reverse_violations,
    raise_milestone_forward_if_violations,
    raise_milestone_reverse_if_violations,
)
from .....shared.labels import (
    KIND_MILESTONE,
    build_label_index_for_project,
    resolve_labels_to_ids,
)
from ...projects.services.audit import (
    ACTION_MILESTONE_DEP_CHANGE,
    ACTION_MILESTONE_UPDATE,
    record_audit,
)


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _gate_milestone_status_against_deps(
    db: Session, milestone_id: str, target_status: str,
) -> None:
    """Doc 31 (rule 2c): block flipping a milestone's status to
    ``completed`` while any of its dependency targets is not yet
    ``completed``. Mirrors the activity-side gate in
    ``activities/services/update.py``.

    Only fires when ``target_status == 'completed'`` — moving back to
    ``not_completed`` is always allowed (matches activity semantics).
    """
    if target_status != MILESTONE_STATUS_COMPLETED:
        return
    dep_repo = DependencyRepository(db)
    target_ids = dep_repo.list_milestone_dependencies(milestone_id)
    if not target_ids:
        return
    rows = (
        db.query(MilestoneModel.id, MilestoneModel.name, MilestoneModel.status)
        .filter(MilestoneModel.id.in_(target_ids))
        .all()
    )
    blockers = [
        (row[0], row[1], row[2])
        for row in rows
        if (row[2] or "") != MILESTONE_STATUS_COMPLETED
    ]
    if blockers:
        names = ", ".join(f"'{b[1]}'" for b in blockers[:3])
        more = "" if len(blockers) <= 3 else f" (+{len(blockers) - 3} more)"
        raise ValidationError(
            f"Cannot mark this milestone as completed — the following "
            f"dependency target(s) are not yet completed: {names}{more}.",
        )


def _gate_milestone_status_against_children(
    db: Session, milestone_id: str, target_status: str,
) -> None:
    """Block flipping a milestone's status to ``completed`` while any
    of its child activities is not yet ``completed``.

    A milestone represents the work below it; closing it out while
    activities under it are still in progress would lose information.
    Only fires on the completed transition; other status flips (back
    to ``not_completed``, or to any future state) are always allowed.

    Soft-deleted activities are ignored — they're considered out of
    scope for the completion rollup.
    """
    if target_status != MILESTONE_STATUS_COMPLETED:
        return
    rows = (
        db.query(ActivityModel.id, ActivityModel.name, ActivityModel.status)
        .filter(ActivityModel.milestone_id == milestone_id)
        .filter(ActivityModel.deleted_at.is_(None))
        .all()
    )
    if not rows:
        # No children — nothing to block. (e.g. milestone created with
        # status='completed' before any activity is attached.)
        return
    blockers = [
        (row[0], row[1], row[2])
        for row in rows
        if (row[2] or "") != MILESTONE_STATUS_COMPLETED
    ]
    if blockers:
        names = ", ".join(f"'{b[1]}'" for b in blockers[:3])
        more = "" if len(blockers) <= 3 else f" (+{len(blockers) - 3} more)"
        raise ValidationError(
            f"Cannot mark this milestone as completed — the following "
            f"child activit{'y' if len(blockers) == 1 else 'ies'} "
            f"{'is' if len(blockers) == 1 else 'are'} not yet completed: "
            f"{names}{more}.",
        )


def update_milestone(
    db: Session,
    *,
    milestone_id: str,
    name: Optional[str],
    description: Optional[str],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    position: Optional[int],
    current_user_id: Optional[int],
    status: Optional[str] = None,
    depends_on: Optional[List[str]] = None,
    vendor_ids: Optional[List[str]] = None,
) -> Milestone:
    repo = MilestoneRepository(db)
    model = repo.get_model(milestone_id)
    if model is None:
        raise NotFoundError("The milestone could not be found.")

    assert_milestone_activity_writable(db, model.project_id)

    project = db.query(ProjectModel).filter(ProjectModel.id == model.project_id).first()
    if project is None or project.start_date is None:
        raise NotFoundError(
            "The project this milestone belongs to could not be found or has no start date."
        )

    new_start = start_date if start_date is not None else model.start_date
    new_end = end_date if end_date is not None else model.end_date

    validate_entity_dates(
        entity_start=new_start,
        entity_end=new_end,
        actual_start=None,
        actual_end=None,
        parent_start_date=project.start_date,
        project_start_date=project.start_date,
        entity_label="milestone",
        parent_label="project",
    )

    if status is not None:
        # Doc 37 part 1: catalog-first; fallback to in-code tuple.
        from .....infrastructure.db.models.milestone_status import (
            MilestoneStatusModel,
        )
        from .....shared.static_catalog import active_codes, is_known_code
        if not is_known_code(
            db, status,
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

    # Doc 31 (rule 2c): status-completion gate. Run before any dep-date
    # work below — if the caller is trying to mark this completed but a
    # dep target isn't, fail fast with the dep names.
    if status is not None:
        _gate_milestone_status_against_deps(db, milestone_id, status)
        # Children-completion gate: a milestone may only flip to
        # ``completed`` when every child activity under it is also
        # ``completed``. Mirrors the dep-target gate above but checks
        # the parent-child rollup instead of cross-edges.
        _gate_milestone_status_against_children(db, milestone_id, status)

    # Validate depends_on (replace-list semantics) BEFORE writing.
    # Accepts UUIDs or labels (e.g. "M2"); see app/shared/labels.py.
    desired_deps: Optional[List[str]] = None
    if depends_on is not None:
        dep_repo = DependencyRepository(db)
        candidates, _id_to_raw = resolve_labels_to_ids(
            db,
            project_id=model.project_id,
            expected_kind=KIND_MILESTONE,
            raw_inputs=depends_on,
        )
        if candidates:
            # Existence check (folded into the below cycle/missing logic
            # for tighter error messages — keeps the per-target raise).
            ok = dep_repo.existing_target_milestone_ids(model.project_id, candidates)
            missing = [d for d in candidates if d not in ok]
            if missing:
                raise ValidationError(
                    f"Unknown or out-of-project milestone dependency target(s): "
                    f"{', '.join(missing)}"
                )
            offending = dep_repo.would_create_cycle_milestone(
                milestone_id, candidates,
            )
            if offending is not None:
                if offending == milestone_id:
                    raise ValidationError(
                        "A milestone cannot depend on itself."
                    )
                raise ValidationError(
                    f"Adding milestone dependency on {offending} would "
                    "create a cycle."
                )
        desired_deps = candidates

    # Doc 31: milestone-specific dep-date rules (replaces the doc 27
    # generic source.start >= target.end rule for milestones only).
    #   2a: source.start_date >= target.start_date  (equality OK)
    #   2b: source.end_date   >  target.end_date    (strict)
    effective_start = start_date if start_date is not None else model.start_date
    effective_end = end_date if end_date is not None else model.end_date
    label_index = None

    # FORWARD: re-validate this milestone's effective dates against its
    # outgoing dep set. Runs when the dep set is being replaced OR when
    # the source's dates moved.
    forward_targets_to_check: List[str]
    if desired_deps is not None:
        forward_targets_to_check = desired_deps
    elif start_date is not None or end_date is not None:
        forward_targets_to_check = DependencyRepository(db) \
            .list_milestone_dependencies(milestone_id)
    else:
        forward_targets_to_check = []
    if forward_targets_to_check:
        target_rows = (
            db.query(
                MilestoneModel.id, MilestoneModel.name,
                MilestoneModel.start_date, MilestoneModel.end_date,
            )
            .filter(MilestoneModel.id.in_(forward_targets_to_check))
            .all()
        )
        if label_index is None:
            label_index = build_label_index_for_project(db, model.project_id)
        forward = [
            (label_index.label_of(KIND_MILESTONE, tid) or tname, tstart, tend)
            for (tid, tname, tstart, tend) in target_rows
        ]
        starts, ends = collect_milestone_forward_violations(
            source_start=effective_start,
            source_end=effective_end,
            targets=forward,
        )
        raise_milestone_forward_if_violations(
            starts, ends,
            source_label=(
                f"Milestone '{label_index.label_of(KIND_MILESTONE, milestone_id) or model.name}'"
            ),
            source_start=effective_start,
            source_end=effective_end,
        )

    # REVERSE: when this milestone's start_date or end_date moves, walk
    # every live source pointing AT it and re-validate against the new
    # values. Either-direction edit triggers the walk because both rules
    # use both columns of the target.
    if start_date is not None or end_date is not None:
        sources = (
            db.query(
                MilestoneModel.id, MilestoneModel.name,
                MilestoneModel.start_date, MilestoneModel.end_date,
            )
            .join(
                MilestoneDependencyModel,
                MilestoneDependencyModel.source_milestone_id == MilestoneModel.id,
            )
            .filter(MilestoneDependencyModel.target_milestone_id == milestone_id)
            .filter(MilestoneDependencyModel.deleted_at.is_(None))
            .filter(MilestoneModel.deleted_at.is_(None))
            .all()
        )
        if sources:
            if label_index is None:
                label_index = build_label_index_for_project(db, model.project_id)
            rev = [
                (label_index.label_of(KIND_MILESTONE, sid) or sname, sstart, send)
                for (sid, sname, sstart, send) in sources
            ]
            r_starts, r_ends = collect_milestone_reverse_violations(
                target_start=effective_start,
                target_end=effective_end,
                sources=rev,
            )
            raise_milestone_reverse_if_violations(
                r_starts, r_ends,
                target_label=(
                    f"Milestone '{label_index.label_of(KIND_MILESTONE, milestone_id) or model.name}'"
                ),
                target_start=effective_start,
                target_end=effective_end,
            )

    updates = {}
    if name is not None:
        updates["name"] = name.strip()
    if description is not None:
        updates["description"] = description
    if start_date is not None:
        updates["start_date"] = start_date
    if end_date is not None:
        updates["end_date"] = end_date
    if position is not None:
        updates["position"] = position
    if status is not None:
        updates["status"] = status

    vendor_repo = VendorRepository(db)
    will_replace_vendors = vendor_ids is not None
    resolved_vendor_ids: List[str] = []
    if will_replace_vendors:
        # Doc 25: each entry can be a UUID or a ``VN-...`` code.
        unique_input = list(dict.fromkeys(vendor_ids or []))
        if unique_input:
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
            project_vendor_ids = set(vendor_repo.project_vendor_ids(model.project_id))
            not_on_project_tokens = [
                t for (t, rid) in resolved_pairs if rid not in project_vendor_ids
            ]
            if not_on_project_tokens:
                raise ValidationError(
                    f"Vendor(s) not attached to this project: {', '.join(not_on_project_tokens)}. "
                    "Add them to the project first."
                )
            resolved_vendor_ids = canonical_ids

    if not updates and not will_replace_vendors and desired_deps is None:
        return repo._to_domain(model)

    before_snapshot = {k: _iso(getattr(model, k)) for k in updates.keys()} if updates else {}

    if updates:
        updated = repo.update(milestone_id, updates=updates, updated_by=current_user_id)
    else:
        updated = repo._to_domain(model)

    if desired_deps is not None:
        DependencyRepository(db).set_milestone_dependencies(
            milestone_id, model.project_id, desired_deps,
            actor_id=current_user_id,
        )
        db.commit()
        updated.depends_on = list(desired_deps)

    if will_replace_vendors:
        vendor_repo.set_milestone_vendors(milestone_id, resolved_vendor_ids)
        db.commit()
        updated.vendors = vendor_repo.list_milestone_vendors(milestone_id)

    if updates:
        record_audit(
            db,
            project_id=model.project_id,
            actor_id=current_user_id,
            action=ACTION_MILESTONE_UPDATE,
            before={"milestone_id": milestone_id, **before_snapshot},
            after={k: _iso(v) for k, v in updates.items()},
        )
        db.commit()

    if desired_deps is not None:
        # Doc 33: dependency-edge changes get their own audit entry so
        # the change history shows who altered the M-to-M graph and when.
        record_audit(
            db,
            project_id=model.project_id,
            actor_id=current_user_id,
            action=ACTION_MILESTONE_DEP_CHANGE,
            before={"milestone_id": milestone_id},
            after={"milestone_id": milestone_id, "depends_on": list(desired_deps)},
        )
        db.commit()

    return updated
