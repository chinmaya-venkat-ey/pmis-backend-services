"""
Project tree aggregator.

One SELECT per table keyed on the denormalized project_id, then stitched
together in Python via dicts. 7 queries total (milestones, activities,
activity_resources, tasks, task_resources, subtasks, subtask_resources).

Returns a dict ready to serialize via api_response envelope.
"""
from datetime import date as _date_type, datetime
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from sqlalchemy.orm import Session

from ....core.errors import NotFoundError
from ....infrastructure.db.models.project import ProjectModel
from ....infrastructure.db.models.milestone import MilestoneModel
from ....infrastructure.db.models.activity import ActivityModel
from ....infrastructure.db.models.activity_dependency import ActivityDependencyModel
from ....infrastructure.db.models.activity_resource import ActivityResourceModel
from ....infrastructure.db.models.milestone_dependency import MilestoneDependencyModel
from ....infrastructure.db.models.task import TaskModel
from ....infrastructure.db.models.task_dependency import TaskDependencyModel
from ....infrastructure.db.models.task_resource import TaskResourceModel
from ....infrastructure.db.models.subtask import SubtaskModel
from ....infrastructure.db.models.subtask_dependency import SubtaskDependencyModel
from ....infrastructure.db.models.subtask_resource import SubtaskResourceModel
from ....infrastructure.db.models.vendor import VendorModel
from ....shared.datetime import IST, iso_ist
from ....shared.labels import (
    KIND_ACTIVITY,
    KIND_MILESTONE,
    KIND_SUBTASK,
    KIND_TASK,
    build_label_index_for_project,
)


def _iso(v) -> Optional[str]:
    """Emit datetimes in IST with explicit ``+05:30`` offset, matching
    the rest of the wire surface. Naive stored values are treated as
    UTC (per ``UtcDateTime`` storage contract) before conversion."""
    return iso_ist(v)


def _ist_calendar_date(dt: Optional[datetime]) -> Optional[_date_type]:
    """IST-local calendar date for a UtcDateTime column.

    Stored M/A/T/S start/end dates are IST midnight (see
    ``shared.datetime.to_ist_calendar_midnight``); ``.date()`` on a
    UTC-stored value would shift the calendar by 5h30m, so we explicitly
    convert to IST first.
    """
    if dt is None:
        return None
    # Stored values are tz-aware UTC after the UtcDateTime bind. Naive
    # values in old test fixtures are treated as UTC for safety.
    if dt.tzinfo is None:
        from datetime import timezone as _tz
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(IST).date()


def _schedule_status(
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    today: _date_type,
) -> Tuple[str, Optional[int]]:
    """Compute schedule status + delay days from expected start/end only.

    Returns a tuple ``(status, days_delayed)`` where:
      * ``status`` is one of ``"not_started"``, ``"in_progress"``,
        ``"delayed"``.
      * ``days_delayed`` is the integer count of calendar days past the
        expected end date when ``status == "delayed"``; ``None``
        otherwise. Callers omit the field from the response unless it's
        non-None.

    Logic is purely based on **expected** start/end dates and the IST
    calendar today — actual dates are intentionally not consulted.
    Rationale: the field answers "is this on schedule?", not "is this
    done?". Items completed before/on their deadline still appear as
    ``in_progress`` until ``today > end_date``; items completed late
    appear as ``delayed`` (the delay calc uses ``end_date``, not the
    actual completion date).

    Defensive default for legacy rows missing one of the dates:
    ``("not_started", None)``.
    """
    if start_date is None or end_date is None:
        return "not_started", None
    sd = _ist_calendar_date(start_date)
    ed = _ist_calendar_date(end_date)
    if sd is None or ed is None:
        return "not_started", None
    if today < sd:
        return "not_started", None
    if today <= ed:
        return "in_progress", None
    return "delayed", (today - ed).days


def _attach_schedule_status(
    payload: Dict[str, Any],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    today: _date_type,
) -> Dict[str, Any]:
    """Add ``scheduleStatus`` (always) and ``daysDelayed`` (only when
    delayed) to ``payload`` in place, returning the same dict for
    fluent use."""
    status, delay = _schedule_status(start_date, end_date, today)
    payload["scheduleStatus"] = status
    if delay is not None:
        payload["daysDelayed"] = delay
    return payload


def _resource_payload(r) -> Dict[str, Any]:
    """Serialize any of the three *Resource models to JSON (same shape)."""
    return {
        "id": r.id,
        "resourceName": r.resource_name,
        "onboardDate": _iso(r.onboard_date),
        "actualOnboardDate": _iso(r.actual_onboard_date),
        "offboardDate": _iso(r.offboard_date),
        "actualOffboardDate": _iso(r.actual_offboard_date),
        "position": r.position,
        "designation": r.designation,
        "jobRole": r.job_role,
        "qualification": r.qualification,
        "experienceYears": float(r.experience_years) if r.experience_years is not None else None,
    }


def build_project_tree(db: Session, project_id: str, include_deleted: bool = False) -> Dict[str, Any]:
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if project is None:
        raise NotFoundError(f"Project with ID {project_id} not found")
    if not include_deleted and getattr(project, "deleted_at", None) is not None:
        raise NotFoundError(f"Project with ID {project_id} has been deleted")

    # Single "today" reference for the entire tree — sampled once so every
    # node gets a consistent verdict even on a slow request that straddles
    # IST midnight.
    today_ist: _date_type = datetime.now(IST).date()

    # All queries filter by the denormalized project_id (one index per table).
    def _q(model):
        q = db.query(model).filter(model.project_id == project_id)
        if not include_deleted:
            q = q.filter(model.deleted_at.is_(None))
        return q

    milestones = _q(MilestoneModel).order_by(MilestoneModel.position.asc(), MilestoneModel.id.asc()).all()
    activities = _q(ActivityModel).order_by(ActivityModel.position.asc(), ActivityModel.id.asc()).all()
    act_resources = _q(ActivityResourceModel).all()

    # One-shot vendor lookup so each activity node can emit ``vendorName``
    # next to ``vendorId``. The FE consumes the tree to render dependency
    # graphs and was forced to do a second round-trip per vendorId before
    # this — pre-loading here keeps it to a single query per tree call.
    vendor_ids: set = {a.vendor_id for a in activities if a.vendor_id}
    vendor_name_by_id: Dict[str, str] = {}
    if vendor_ids:
        for vid, vname in (
            db.query(VendorModel.id, VendorModel.name)
            .filter(VendorModel.id.in_(vendor_ids))
            .all()
        ):
            vendor_name_by_id[vid] = vname
    tasks = _q(TaskModel).order_by(TaskModel.position.asc(), TaskModel.id.asc()).all()
    task_resources = _q(TaskResourceModel).all()
    subtasks = _q(SubtaskModel).order_by(SubtaskModel.position.asc(), SubtaskModel.id.asc()).all()
    sub_resources = _q(SubtaskResourceModel).all()

    # Bulk-load dependency edges scoped to this project (4 queries — one per
    # association table). Store as dicts keyed by source id -> list of target
    # ids so each node render is O(1).
    milestone_deps_by_source: Dict[str, List[str]] = defaultdict(list)
    for src, tgt in (
        db.query(
            MilestoneDependencyModel.source_milestone_id,
            MilestoneDependencyModel.target_milestone_id,
        )
        .filter(MilestoneDependencyModel.project_id == project_id)
        .filter(MilestoneDependencyModel.deleted_at.is_(None))
        .all()
    ):
        milestone_deps_by_source[src].append(tgt)

    act_deps_by_source: Dict[str, List[str]] = defaultdict(list)
    for src, tgt in (
        db.query(
            ActivityDependencyModel.source_activity_id,
            ActivityDependencyModel.target_activity_id,
        )
        .filter(ActivityDependencyModel.project_id == project_id)
        .filter(ActivityDependencyModel.deleted_at.is_(None))
        .all()
    ):
        act_deps_by_source[src].append(tgt)

    task_deps_by_source: Dict[str, List[str]] = defaultdict(list)
    for src, tgt in (
        db.query(
            TaskDependencyModel.source_task_id,
            TaskDependencyModel.target_task_id,
        )
        .filter(TaskDependencyModel.project_id == project_id)
        .filter(TaskDependencyModel.deleted_at.is_(None))
        .all()
    ):
        task_deps_by_source[src].append(tgt)

    # Build the label index ONCE per tree request (4 queries — one per
    # M/A/T/S level). Used to populate displayCode + dependsOnDisplay on
    # every node in the response.
    label_idx = build_label_index_for_project(db, project_id)

    subtask_deps_by_source: Dict[str, List[str]] = defaultdict(list)
    for src, tgt in (
        db.query(
            SubtaskDependencyModel.source_subtask_id,
            SubtaskDependencyModel.target_subtask_id,
        )
        .filter(SubtaskDependencyModel.project_id == project_id)
        .filter(SubtaskDependencyModel.deleted_at.is_(None))
        .all()
    ):
        subtask_deps_by_source[src].append(tgt)

    # Group children by their immediate parent for O(1) lookup during stitch.
    acts_by_milestone: Dict[int, List[ActivityModel]] = defaultdict(list)
    for a in activities:
        acts_by_milestone[a.milestone_id].append(a)

    ar_by_act: Dict[int, ActivityResourceModel] = {r.activity_id: r for r in act_resources}

    tasks_by_activity: Dict[int, List[TaskModel]] = defaultdict(list)
    for t in tasks:
        tasks_by_activity[t.activity_id].append(t)

    tr_by_task: Dict[int, TaskResourceModel] = {r.task_id: r for r in task_resources}

    # Doc 24: subtasks can nest. Group top-level under their root task,
    # and group every other subtask under its immediate parent subtask.
    top_subs_by_task: Dict[str, List[SubtaskModel]] = defaultdict(list)
    children_by_parent_sub: Dict[str, List[SubtaskModel]] = defaultdict(list)
    for s in subtasks:
        if getattr(s, "parent_subtask_id", None) is None:
            top_subs_by_task[s.task_id].append(s)
        else:
            children_by_parent_sub[s.parent_subtask_id].append(s)

    sr_by_sub: Dict[int, SubtaskResourceModel] = {r.subtask_id: r for r in sub_resources}

    # --- Stitch bottom-up ---
    def subtask_node(s: SubtaskModel) -> Dict[str, Any]:
        # Resource row exists only in details mode; count mode uses resource_count.
        resource = (
            sr_by_sub.get(s.id)
            if s.type == "resource" and getattr(s, "resource_mode", None) == "details"
            else None
        )
        deps = sorted(subtask_deps_by_source.get(s.id, []))
        payload = {
            "id": s.id,
            "displayCode": label_idx.label_of(KIND_SUBTASK, s.id),
            "taskId": s.task_id, "projectId": s.project_id,
            "parentSubtaskId": getattr(s, "parent_subtask_id", None),
            "name": s.name, "description": s.description, "type": s.type,
            "status": getattr(s, "status", None),
            "startDate": _iso(s.start_date), "endDate": _iso(s.end_date),
            "actualStartDate": _iso(s.actual_start_date),
            "actualEndDate": _iso(s.actual_end_date),
            "position": s.position,
            "resourceMode": getattr(s, "resource_mode", None),
            "resourceCount": getattr(s, "resource_count", None),
            "dependsOn": deps,
            "dependsOnDisplay": label_idx.labels_of(KIND_SUBTASK, deps),
            "deletedAt": _iso(s.deleted_at),
            "resource": _resource_payload(resource) if resource else None,
            # Doc 24: nested children rendered recursively. Empty list for
            # leaves keeps the FE iteration simple (no `if subtasks`).
            "subtasks": [
                subtask_node(child)
                for child in children_by_parent_sub.get(s.id, [])
            ],
        }
        return _attach_schedule_status(payload, s.start_date, s.end_date, today_ist)

    def task_node(t: TaskModel) -> Dict[str, Any]:
        resource = (
            tr_by_task.get(t.id)
            if t.type == "resource" and getattr(t, "resource_mode", None) == "details"
            else None
        )
        deps = sorted(task_deps_by_source.get(t.id, []))
        payload = {
            "id": t.id,
            "displayCode": label_idx.label_of(KIND_TASK, t.id),
            "activityId": t.activity_id, "projectId": t.project_id,
            "name": t.name, "description": t.description, "type": t.type,
            "status": getattr(t, "status", None),
            "startDate": _iso(t.start_date), "endDate": _iso(t.end_date),
            "actualStartDate": _iso(t.actual_start_date),
            "actualEndDate": _iso(t.actual_end_date),
            "position": t.position,
            "resourceMode": getattr(t, "resource_mode", None),
            "resourceCount": getattr(t, "resource_count", None),
            "dependsOn": deps,
            "dependsOnDisplay": label_idx.labels_of(KIND_TASK, deps),
            "deletedAt": _iso(t.deleted_at),
            "resource": _resource_payload(resource) if resource else None,
            "subtasks": [
                subtask_node(s) for s in top_subs_by_task.get(t.id, [])
            ],
        }
        return _attach_schedule_status(payload, t.start_date, t.end_date, today_ist)

    def activity_node(a: ActivityModel) -> Dict[str, Any]:
        resource = (
            ar_by_act.get(a.id)
            if a.type == "resource" and getattr(a, "resource_mode", None) == "details"
            else None
        )
        deps = sorted(act_deps_by_source.get(a.id, []))
        payload = {
            "id": a.id,
            "displayCode": label_idx.label_of(KIND_ACTIVITY, a.id),
            "milestoneId": a.milestone_id, "projectId": a.project_id,
            "name": a.name, "description": a.description, "type": a.type,
            "status": getattr(a, "status", None),
            # Doc 39 ownership fields. ``concernedDivision`` keyword
            # preserved on the wire for FE compat; datatype is now a
            # list. Legacy single-value column on disk is kept but
            # never surfaced.
            "ownerDivision": getattr(a, "owner_division", None),
            "concernedDivision": getattr(a, "concerned_divisions", None) or [],
            "vendorId": getattr(a, "vendor_id", None),
            # Vendor name pulled from the bulk lookup above. Null when the
            # activity has no vendor or the vendor row has been hard-deleted
            # (soft-delete is fine — name still resolves).
            "vendorName": vendor_name_by_id.get(getattr(a, "vendor_id", None)),
            # Doc 41: priority code from the priorities catalog.
            "priority": getattr(a, "priority", None),
            "startDate": _iso(a.start_date), "endDate": _iso(a.end_date),
            "actualStartDate": _iso(a.actual_start_date),
            "actualEndDate": _iso(a.actual_end_date),
            "position": a.position,
            "resourceMode": getattr(a, "resource_mode", None),
            "resourceCount": getattr(a, "resource_count", None),
            "dependsOn": deps,
            "dependsOnDisplay": label_idx.labels_of(KIND_ACTIVITY, deps),
            "deletedAt": _iso(a.deleted_at),
            "resource": _resource_payload(resource) if resource else None,
            "tasks": [task_node(t) for t in tasks_by_activity.get(a.id, [])],
        }
        return _attach_schedule_status(payload, a.start_date, a.end_date, today_ist)

    def milestone_node(m: MilestoneModel) -> Dict[str, Any]:
        deps = sorted(milestone_deps_by_source.get(m.id, []))
        payload = {
            "id": m.id,
            "displayCode": label_idx.label_of(KIND_MILESTONE, m.id),
            "projectId": m.project_id,
            "name": m.name, "description": m.description,
            "startDate": _iso(m.start_date), "endDate": _iso(m.end_date),
            "position": m.position,
            "status": getattr(m, "status", None),
            "dependsOn": deps,
            "dependsOnDisplay": label_idx.labels_of(KIND_MILESTONE, deps),
            "deletedAt": _iso(m.deleted_at),
            "activities": [activity_node(a) for a in acts_by_milestone.get(m.id, [])],
        }
        return _attach_schedule_status(payload, m.start_date, m.end_date, today_ist)

    tree_milestones = [milestone_node(m) for m in milestones]

    # Small counts block for observability -- useful for UI and tests.
    counts = {
        "milestones": len(milestones),
        "activities": len(activities),
        "tasks": len(tasks),
        "subtasks": len(subtasks),
        "activityResources": len(act_resources),
        "taskResources": len(task_resources),
        "subtaskResources": len(sub_resources),
    }

    # project.id IS the public UUID handle (no separate uuid column).
    project_id = project.id
    return {
        "_type": "ProjectTree",
        "_links": {
            "self": {"href": f"/api/v3/projects/{project_id}/tree" if project_id else None},
            "project": {"href": f"/api/v3/projects/{project_id}" if project_id else None},
        },
        "project": {
            "id": project_id,
            "projectCode": getattr(project, "project_code", None),
            "name": getattr(project, "name", None),
            "description": getattr(project, "description", None),
            "status": getattr(project, "status", None),
            "owner": getattr(project, "owner", None),
            "category": getattr(project, "category", None),
            "startDate": _iso(getattr(project, "start_date", None)),
            "endDate": _iso(getattr(project, "end_date", None)),
            "isPublic": getattr(project, "public", None),
        },
        "counts": counts,
        "milestones": tree_milestones,
    }
