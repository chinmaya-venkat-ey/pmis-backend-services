"""
Propagate baseline milestone / activity changes to active versions.

Call one of the ``propagate_*`` functions after a baseline M/A write has
been applied. The helper walks the version-side lineage (milestones and
activities remember their ``cloned_from_id``) and mirrors the change on
every *active* version, stamping a matching audit row per version.

Active version = ``is_version = True AND deleted_at IS NULL AND
status NOT IN ('suspended', 'closed')``. A suspended or closed version is
considered dormant and does not receive further propagation.

Each propagator commits its own work — callers are services that have
already committed the baseline write, so by the time we run the baseline
row is durable. Audit rows are flushed and committed alongside the
propagated write so baseline change + audit trail remain atomic per
version.

Field selection
---------------
For updates we carry forward the "shape" columns (name, description,
start/end/position, plus resource_mode/resource_count/type on activities)
but deliberately NOT ``status``, ``depends`` or ``dependency`` — those are
version-local: each version tracks its own progress, and dependency id
lists reference sibling rows that differ between versions.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session

from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.models.activity_resource import ActivityResourceModel
from .....infrastructure.db.models.milestone import MilestoneModel
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.subtask import SubtaskModel
from .....infrastructure.db.models.subtask_resource import SubtaskResourceModel
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.models.task_resource import TaskResourceModel

from .audit import record_audit


# Audit action names for baseline-originated changes on M/A. Used for both
# the baseline write and for each version twin affected by the cascade.
ACTION_MILESTONE_CREATE = "milestone.create"
ACTION_MILESTONE_UPDATE = "milestone.update"
ACTION_MILESTONE_DELETE = "milestone.soft_delete"
ACTION_ACTIVITY_CREATE = "activity.create"
ACTION_ACTIVITY_UPDATE = "activity.update"
ACTION_ACTIVITY_DELETE = "activity.soft_delete"

ACTION_MILESTONE_CREATE_CASCADE = "milestone.create.cascade_from_baseline"
ACTION_MILESTONE_UPDATE_CASCADE = "milestone.update.cascade_from_baseline"
ACTION_MILESTONE_DELETE_CASCADE = "milestone.soft_delete.cascade_from_baseline"
ACTION_ACTIVITY_CREATE_CASCADE = "activity.create.cascade_from_baseline"
ACTION_ACTIVITY_UPDATE_CASCADE = "activity.update.cascade_from_baseline"
ACTION_ACTIVITY_DELETE_CASCADE = "activity.soft_delete.cascade_from_baseline"


# Fields whose value we mirror from a baseline M/A update onto version twins.
_MILESTONE_PROPAGATED_FIELDS = ("name", "description", "start_date", "end_date", "position")
_ACTIVITY_PROPAGATED_FIELDS = (
    "name",
    "description",
    "type",
    "start_date",
    "end_date",
    "position",
    "resource_mode",
    "resource_count",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _active_version_ids(db: Session, baseline_project_id: str) -> List[str]:
    """
    Version projects that should receive propagated baseline edits.

    A version is eligible when it is live (not soft-deleted) and not in a
    dormant state (``suspended``, ``closed``). ``new``, ``draft``, and
    ``published`` versions all receive updates — the rule is "if the
    version is still being worked on, keep it in sync with the baseline".
    """
    rows = (
        db.query(ProjectModel.id)
        .filter(
            and_(
                ProjectModel.version_of == baseline_project_id,
                ProjectModel.is_version.is_(True),
                ProjectModel.deleted_at.is_(None),
                ProjectModel.status.notin_(("suspended", "closed")),
            )
        )
        .all()
    )
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Milestone propagation
# ---------------------------------------------------------------------------


def propagate_milestone_create(
    db: Session,
    *,
    baseline_milestone_id: str,
    actor_id: Optional[int],
) -> int:
    """
    Mirror a newly-created baseline milestone into every active version.

    Each version gets its own milestone row (fresh uuid), with
    ``cloned_from_id`` pointing at the baseline milestone so future edits
    can find it again. Returns the number of version clones created.
    """
    baseline = db.query(MilestoneModel).filter(MilestoneModel.id == baseline_milestone_id).first()
    if baseline is None or baseline.deleted_at is not None:
        return 0

    version_ids = _active_version_ids(db, baseline.project_id)
    if not version_ids:
        return 0

    now = _utcnow()
    created = 0
    for vid in version_ids:
        new = MilestoneModel(
            project_id=vid,
            name=baseline.name,
            description=baseline.description,
            start_date=baseline.start_date,
            end_date=baseline.end_date,
            position=baseline.position,
            # Status/depends are version-local: fresh version milestones
            # start in the default state with no dependency graph carried.
            status="not_completed",
            depends=None,
            cloned_from_id=baseline.id,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(new)
        db.flush()
        record_audit(
            db,
            project_id=vid,
            actor_id=actor_id,
            action=ACTION_MILESTONE_CREATE_CASCADE,
            before=None,
            after={
                "milestone_id": new.id,
                "cloned_from_baseline_milestone_id": baseline.id,
                "name": new.name,
            },
        )
        created += 1
    db.commit()
    return created


def propagate_milestone_update(
    db: Session,
    *,
    baseline_milestone_id: str,
    updates: Dict[str, Any],
    actor_id: Optional[int],
) -> int:
    """
    Apply the same field patch to every active-version twin.

    ``updates`` is the dict the baseline service used; we intersect it
    with the version-safe field list (``status`` and ``depends`` drop out).
    Returns the number of version rows patched.
    """
    safe_updates = {
        k: v for k, v in updates.items() if k in _MILESTONE_PROPAGATED_FIELDS
    }
    if not safe_updates:
        return 0

    twins = (
        db.query(MilestoneModel)
        .filter(
            and_(
                MilestoneModel.cloned_from_id == baseline_milestone_id,
                MilestoneModel.deleted_at.is_(None),
            )
        )
        .all()
    )
    if not twins:
        return 0

    # Filter to twins that belong to an active version.
    baseline_project_id = twins[0].project_id if False else None  # placeholder
    # We must derive the baseline project id from the baseline row to know
    # which versions count as active.
    baseline = db.query(MilestoneModel).filter(MilestoneModel.id == baseline_milestone_id).first()
    if baseline is None:
        return 0
    active_vid_set = set(_active_version_ids(db, baseline.project_id))
    twins = [t for t in twins if t.project_id in active_vid_set]
    if not twins:
        return 0

    now = _utcnow()
    count = 0
    for twin in twins:
        before = {k: _isoformat_if_date(getattr(twin, k)) for k in safe_updates.keys()}
        for k, v in safe_updates.items():
            setattr(twin, k, v)
        twin.updated_at = now
        twin.updated_by = actor_id
        after = {k: _isoformat_if_date(getattr(twin, k)) for k in safe_updates.keys()}
        db.flush()
        record_audit(
            db,
            project_id=twin.project_id,
            actor_id=actor_id,
            action=ACTION_MILESTONE_UPDATE_CASCADE,
            before={
                "milestone_id": twin.id,
                "cloned_from_baseline_milestone_id": baseline_milestone_id,
                **before,
            },
            after=after,
        )
        count += 1
    db.commit()
    return count


def propagate_milestone_soft_delete(
    db: Session,
    *,
    baseline_milestone_id: str,
    actor_id: Optional[int],
) -> int:
    """
    Soft-delete every version twin (and its subtree) in active versions.
    """
    baseline = (
        db.query(MilestoneModel)
        .filter(MilestoneModel.id == baseline_milestone_id)
        .first()
    )
    if baseline is None:
        return 0
    baseline_project_id = baseline.project_id

    active_vid_set = set(_active_version_ids(db, baseline_project_id))
    if not active_vid_set:
        return 0

    twins = (
        db.query(MilestoneModel)
        .filter(
            and_(
                MilestoneModel.cloned_from_id == baseline_milestone_id,
                MilestoneModel.deleted_at.is_(None),
                MilestoneModel.project_id.in_(active_vid_set),
            )
        )
        .all()
    )
    if not twins:
        return 0

    now = _utcnow()
    count = 0
    # Local import to avoid circularity.
    from .....infrastructure.db.repositories.dependency_repository import (
        DependencyRepository,
    )
    dep_repo = DependencyRepository(db)

    for twin in twins:
        # Collect the full A/T/S subtree for this twin BEFORE soft-delete.
        twin_activity_ids = [
            r[0]
            for r in db.execute(
                select(ActivityModel.id).where(
                    ActivityModel.milestone_id == twin.id,
                    ActivityModel.deleted_at.is_(None),
                )
            ).all()
        ]
        twin_task_ids: list = []
        twin_subtask_ids: list = []
        if twin_activity_ids:
            twin_task_ids = [
                r[0]
                for r in db.execute(
                    select(TaskModel.id).where(
                        TaskModel.activity_id.in_(twin_activity_ids),
                        TaskModel.deleted_at.is_(None),
                    )
                ).all()
            ]
            if twin_task_ids:
                twin_subtask_ids = [
                    r[0]
                    for r in db.execute(
                        select(SubtaskModel.id).where(
                            SubtaskModel.task_id.in_(twin_task_ids),
                            SubtaskModel.deleted_at.is_(None),
                        )
                    ).all()
                ]
        # Soft-delete all dep edges across this twin's subtree.
        dep_repo.cascade_remove_for_deleted_milestone_subtree(
            twin_activity_ids, twin_task_ids, twin_subtask_ids,
            actor_id=actor_id,
        )

        _soft_delete_milestone_subtree(db, twin.id, actor_id=actor_id, now=now)
        record_audit(
            db,
            project_id=twin.project_id,
            actor_id=actor_id,
            action=ACTION_MILESTONE_DELETE_CASCADE,
            before={
                "milestone_id": twin.id,
                "cloned_from_baseline_milestone_id": baseline_milestone_id,
                "name": twin.name,
            },
            after=None,
        )
        count += 1
    db.commit()
    return count


# ---------------------------------------------------------------------------
# Activity propagation
# ---------------------------------------------------------------------------


def propagate_activity_create(
    db: Session,
    *,
    baseline_activity_id: str,
    actor_id: Optional[int],
) -> int:
    """
    Mirror a newly-created baseline activity into every active version.

    The version twin attaches to whichever milestone in the version was
    cloned from this activity's baseline milestone. If no such milestone
    exists in a version (unusual — typically means the version predates
    that baseline milestone too), the propagation for that version is
    skipped silently; its audit trail will show nothing for this change.
    """
    baseline = (
        db.query(ActivityModel)
        .filter(ActivityModel.id == baseline_activity_id)
        .first()
    )
    if baseline is None or baseline.deleted_at is not None:
        return 0

    active_vids = _active_version_ids(db, baseline.project_id)
    if not active_vids:
        return 0

    # Find each version's twin of the baseline's parent milestone.
    version_milestone_twins = (
        db.query(MilestoneModel)
        .filter(
            and_(
                MilestoneModel.cloned_from_id == baseline.milestone_id,
                MilestoneModel.deleted_at.is_(None),
                MilestoneModel.project_id.in_(active_vids),
            )
        )
        .all()
    )
    # Map: version_project_id -> twin milestone id
    vid_to_mid: Dict[str, str] = {m.project_id: m.id for m in version_milestone_twins}

    now = _utcnow()
    created = 0
    for vid in active_vids:
        twin_milestone_id = vid_to_mid.get(vid)
        if twin_milestone_id is None:
            continue
        new = ActivityModel(
            project_id=vid,
            milestone_id=twin_milestone_id,
            name=baseline.name,
            description=baseline.description,
            type=baseline.type,
            start_date=baseline.start_date,
            end_date=baseline.end_date,
            actual_start_date=None,
            actual_end_date=None,
            position=baseline.position,
            resource_mode=baseline.resource_mode,
            resource_count=baseline.resource_count,
            status="not_completed" if baseline.type == "standard" else None,
            dependency=None,
            cloned_from_id=baseline.id,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(new)
        db.flush()
        record_audit(
            db,
            project_id=vid,
            actor_id=actor_id,
            action=ACTION_ACTIVITY_CREATE_CASCADE,
            before=None,
            after={
                "activity_id": new.id,
                "cloned_from_baseline_activity_id": baseline.id,
                "name": new.name,
                "type": new.type,
            },
        )
        created += 1
    db.commit()
    return created


def propagate_activity_update(
    db: Session,
    *,
    baseline_activity_id: str,
    updates: Dict[str, Any],
    actor_id: Optional[int],
) -> int:
    """
    Apply matching field patch to active-version twins of this activity.

    ``status`` and ``dependency`` are version-local and drop out.
    """
    safe_updates = {
        k: v for k, v in updates.items() if k in _ACTIVITY_PROPAGATED_FIELDS
    }
    if not safe_updates:
        return 0

    baseline = (
        db.query(ActivityModel)
        .filter(ActivityModel.id == baseline_activity_id)
        .first()
    )
    if baseline is None:
        return 0
    active_vid_set = set(_active_version_ids(db, baseline.project_id))
    if not active_vid_set:
        return 0

    twins = (
        db.query(ActivityModel)
        .filter(
            and_(
                ActivityModel.cloned_from_id == baseline_activity_id,
                ActivityModel.deleted_at.is_(None),
                ActivityModel.project_id.in_(active_vid_set),
            )
        )
        .all()
    )
    if not twins:
        return 0

    now = _utcnow()
    count = 0
    for twin in twins:
        before = {k: _isoformat_if_date(getattr(twin, k)) for k in safe_updates.keys()}
        for k, v in safe_updates.items():
            setattr(twin, k, v)
        twin.updated_at = now
        twin.updated_by = actor_id
        after = {k: _isoformat_if_date(getattr(twin, k)) for k in safe_updates.keys()}
        db.flush()
        record_audit(
            db,
            project_id=twin.project_id,
            actor_id=actor_id,
            action=ACTION_ACTIVITY_UPDATE_CASCADE,
            before={
                "activity_id": twin.id,
                "cloned_from_baseline_activity_id": baseline_activity_id,
                **before,
            },
            after=after,
        )
        count += 1
    db.commit()
    return count


def propagate_activity_soft_delete(
    db: Session,
    *,
    baseline_activity_id: str,
    actor_id: Optional[int],
) -> int:
    """Soft-delete activity twins (and their subtree) on active versions."""
    baseline = (
        db.query(ActivityModel)
        .filter(ActivityModel.id == baseline_activity_id)
        .first()
    )
    if baseline is None:
        return 0
    active_vid_set = set(_active_version_ids(db, baseline.project_id))
    if not active_vid_set:
        return 0

    twins = (
        db.query(ActivityModel)
        .filter(
            and_(
                ActivityModel.cloned_from_id == baseline_activity_id,
                ActivityModel.deleted_at.is_(None),
                ActivityModel.project_id.in_(active_vid_set),
            )
        )
        .all()
    )
    if not twins:
        return 0

    now = _utcnow()
    count = 0
    # Local import to avoid circularity.
    from .....infrastructure.db.repositories.dependency_repository import (
        DependencyRepository,
    )
    dep_repo = DependencyRepository(db)

    for twin in twins:
        # Snapshot the version twin's task/subtask subtree BEFORE soft-delete
        # so the dep-cascade query can find them.
        twin_task_ids = [
            r[0]
            for r in db.execute(
                select(TaskModel.id).where(
                    TaskModel.activity_id == twin.id,
                    TaskModel.deleted_at.is_(None),
                )
            ).all()
        ]
        twin_subtask_ids: list = []
        if twin_task_ids:
            twin_subtask_ids = [
                r[0]
                for r in db.execute(
                    select(SubtaskModel.id).where(
                        SubtaskModel.task_id.in_(twin_task_ids),
                        SubtaskModel.deleted_at.is_(None),
                    )
                ).all()
            ]
        # Wipe all dependency edges that touch this twin's subtree before we
        # soft-delete the rows themselves. Same philosophy as the baseline
        # delete path: silently drop stale edges.
        dep_repo.cascade_remove_for_deleted_activity_subtree(
            twin.id, twin_task_ids, twin_subtask_ids,
            actor_id=actor_id,
        )

        _soft_delete_activity_subtree(db, twin.id, actor_id=actor_id, now=now)
        record_audit(
            db,
            project_id=twin.project_id,
            actor_id=actor_id,
            action=ACTION_ACTIVITY_DELETE_CASCADE,
            before={
                "activity_id": twin.id,
                "cloned_from_baseline_activity_id": baseline_activity_id,
                "name": twin.name,
            },
            after=None,
        )
        count += 1
    db.commit()
    return count


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _soft_delete_milestone_subtree(
    db: Session, milestone_id: str, *, actor_id: Optional[int], now: datetime,
) -> None:
    """Soft-delete one milestone row plus every activity/task/subtask row
    (and their resource rows) beneath it. No commit — caller commits."""
    activity_ids = select(ActivityModel.id).where(
        ActivityModel.milestone_id == milestone_id,
        ActivityModel.deleted_at.is_(None),
    )
    task_ids = select(TaskModel.id).where(
        TaskModel.activity_id.in_(activity_ids),
        TaskModel.deleted_at.is_(None),
    )
    subtask_ids = select(SubtaskModel.id).where(
        SubtaskModel.task_id.in_(task_ids),
        SubtaskModel.deleted_at.is_(None),
    )

    db.execute(update(SubtaskResourceModel).where(
        SubtaskResourceModel.subtask_id.in_(subtask_ids),
        SubtaskResourceModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now))
    db.execute(update(TaskResourceModel).where(
        TaskResourceModel.task_id.in_(task_ids),
        TaskResourceModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now))
    db.execute(update(ActivityResourceModel).where(
        ActivityResourceModel.activity_id.in_(activity_ids),
        ActivityResourceModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now))
    db.execute(update(SubtaskModel).where(
        SubtaskModel.task_id.in_(task_ids),
        SubtaskModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now, updated_by=actor_id))
    db.execute(update(TaskModel).where(
        TaskModel.activity_id.in_(activity_ids),
        TaskModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now, updated_by=actor_id))
    db.execute(update(ActivityModel).where(
        ActivityModel.milestone_id == milestone_id,
        ActivityModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now, updated_by=actor_id))
    db.execute(update(MilestoneModel).where(
        MilestoneModel.id == milestone_id,
        MilestoneModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now, updated_by=actor_id))


def _soft_delete_activity_subtree(
    db: Session, activity_id: str, *, actor_id: Optional[int], now: datetime,
) -> None:
    task_ids = select(TaskModel.id).where(
        TaskModel.activity_id == activity_id,
        TaskModel.deleted_at.is_(None),
    )
    subtask_ids = select(SubtaskModel.id).where(
        SubtaskModel.task_id.in_(task_ids),
        SubtaskModel.deleted_at.is_(None),
    )

    db.execute(update(SubtaskResourceModel).where(
        SubtaskResourceModel.subtask_id.in_(subtask_ids),
        SubtaskResourceModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now))
    db.execute(update(TaskResourceModel).where(
        TaskResourceModel.task_id.in_(task_ids),
        TaskResourceModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now))
    db.execute(update(ActivityResourceModel).where(
        ActivityResourceModel.activity_id == activity_id,
        ActivityResourceModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now))
    db.execute(update(SubtaskModel).where(
        SubtaskModel.task_id.in_(task_ids),
        SubtaskModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now, updated_by=actor_id))
    db.execute(update(TaskModel).where(
        TaskModel.activity_id == activity_id,
        TaskModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now, updated_by=actor_id))
    db.execute(update(ActivityModel).where(
        ActivityModel.id == activity_id,
        ActivityModel.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now, updated_by=actor_id))


def _isoformat_if_date(value: Any) -> Any:
    """JSON-friendly conversion for datetime audit payloads."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value
