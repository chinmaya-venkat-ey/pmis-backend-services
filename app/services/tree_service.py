"""Tree service — full M/A/T/S tree under a project.

Port of the monolith's ``app/api/v3/tree/service.py``. Returns a single
deeply-nested payload (milestones → activities → tasks → subtasks, with
resource sidecars inlined for resource-type entities). The FE depends
on the exact nested shape, so the traversal mirrors the monolith
function-for-function — only the data-access layer is updated to
SQLAlchemy 2.0 ``select(...)`` syntax and to use project-svc model
field names (``from_*_id`` / ``to_*_id`` for dependencies, vs. the
monolith's ``source_*_id`` / ``target_*_id``).

Inline ``LabelIndex`` builder — the monolith's ``app/shared/labels.py``
exposes this as a shared module; project-svc doesn't have an equivalent
yet, so the build pass is folded into this service. Same algorithm:
4 queries (one per kind), then in-Python ranking by ``(position, id)``.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as _date_type, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models._cross_schema import User as MirrorUser, Vendor
from app.models.activity import Activity
from app.models.activity_dependency import ActivityDependency
from app.models.activity_resource import ActivityResource
from app.models.milestone import Milestone
from app.models.milestone_dependency import MilestoneDependency
from app.models.project import Project
from app.models.subtask import Subtask
from app.models.subtask_dependency import SubtaskDependency
from app.models.subtask_resource import SubtaskResource
from app.models.task import Task
from app.models.task_dependency import TaskDependency
from app.models.task_resource import TaskResource
from app.utilities.timezones import IST, iso_ist


# =========================================================================
# Schedule-status derivation (verbatim port of monolith's tree helpers)
# =========================================================================

def _ist_calendar_date(dt: Optional[datetime]) -> Optional[_date_type]:
    """IST-local calendar date for a DateTime(timezone=True) column.

    Stored M/A/T/S start/end dates are IST midnight; ``.date()`` on a
    UTC-stored value would shift the calendar by 5h30m, so we explicitly
    convert to IST first.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).date()


def _schedule_status(
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    today: _date_type,
    actual_start_date: Optional[datetime] = None,
    actual_end_date: Optional[datetime] = None,
) -> Tuple[str, Optional[int]]:
    """Compute schedule status + delay days, preferring actual dates
    when set and falling back to expected dates otherwise.

    Returns ``(status, days_delayed)`` where:
      * ``status`` is one of ``"not_started"`` / ``"in_progress"`` /
        ``"delayed"``.
      * ``days_delayed`` is the integer count of calendar days past
        the effective end date when ``status == "delayed"``;
        ``None`` otherwise.
    """
    eff_start = actual_start_date if actual_start_date is not None else start_date
    eff_end = actual_end_date if actual_end_date is not None else end_date
    if eff_start is None or eff_end is None:
        return "not_started", None
    sd = _ist_calendar_date(eff_start)
    ed = _ist_calendar_date(eff_end)
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
    actual_start_date: Optional[datetime] = None,
    actual_end_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Add ``scheduleStatus`` (always) and ``daysDelayed`` (only when
    delayed) to ``payload`` in place; returns the same dict."""
    status, delay = _schedule_status(
        start_date, end_date, today,
        actual_start_date=actual_start_date,
        actual_end_date=actual_end_date,
    )
    payload["scheduleStatus"] = status
    if delay is not None:
        payload["daysDelayed"] = delay
    return payload


def _resource_payload(r: Any) -> Dict[str, Any]:
    """Serialize any of the three *Resource models to JSON (same shape)."""
    return {
        "id": r.id,
        "resourceName": r.resource_name,
        "onboardDate": iso_ist(r.onboard_date),
        "actualOnboardDate": iso_ist(r.actual_onboard_date),
        "offboardDate": iso_ist(r.offboard_date),
        "actualOffboardDate": iso_ist(r.actual_offboard_date),
        "position": r.position,
        "designation": r.designation,
        "jobRole": r.job_role,
        "qualification": r.qualification,
        "experienceYears": (
            float(r.experience_years) if r.experience_years is not None else None
        ),
    }


# =========================================================================
# Kind constants + inline LabelIndex
# =========================================================================

KIND_MILESTONE = "milestone"
KIND_ACTIVITY = "activity"
KIND_TASK = "task"
KIND_SUBTASK = "subtask"


class _LabelIndex:
    """id -> label maps for one project's M/A/T/S. Built in 4 queries.

    Kept inline (vs. the monolith's shared ``LabelIndex`` dataclass) so
    project-svc doesn't grow a new shared module just for the tree."""

    __slots__ = (
        "milestone_id_to_label",
        "activity_id_to_label",
        "task_id_to_label",
        "subtask_id_to_label",
    )

    def __init__(self) -> None:
        self.milestone_id_to_label: Dict[str, str] = {}
        self.activity_id_to_label: Dict[str, str] = {}
        self.task_id_to_label: Dict[str, str] = {}
        self.subtask_id_to_label: Dict[str, str] = {}

    def for_kind(self, kind: str) -> Dict[str, str]:
        return {
            KIND_MILESTONE: self.milestone_id_to_label,
            KIND_ACTIVITY: self.activity_id_to_label,
            KIND_TASK: self.task_id_to_label,
            KIND_SUBTASK: self.subtask_id_to_label,
        }[kind]

    def label_of(self, kind: str, entity_id: Optional[str]) -> Optional[str]:
        if entity_id is None:
            return None
        return self.for_kind(kind).get(entity_id)

    def labels_of(self, kind: str, ids: List[str]) -> List[str]:
        """Map a list of UUIDs to labels (input order). Unknown ids
        are silently dropped — they're soft-deleted parents or
        cross-project references."""
        m = self.for_kind(kind)
        out: List[str] = []
        for i in ids or []:
            label = m.get(i)
            if label is not None:
                out.append(label)
        return out


def _build_label_index(db: Session, project_id: str) -> _LabelIndex:
    """Build a complete label index for one project (4 queries)."""
    idx = _LabelIndex()

    # ---- Milestones -----------------------------------------------------
    m_stmt = (
        select(Milestone.id, Milestone.position)
        .where(Milestone.project_id == project_id)
        .where(Milestone.deleted_at.is_(None))
        .order_by(asc(Milestone.position), asc(Milestone.id))
    )
    m_id_to_rank: Dict[str, int] = {}
    for m_idx, (mid, _pos) in enumerate(db.execute(m_stmt).all(), start=1):
        idx.milestone_id_to_label[mid] = f"M{m_idx}"
        m_id_to_rank[mid] = m_idx

    # ---- Activities (project-scoped query, rank in Python) -------------
    a_stmt = (
        select(Activity.id, Activity.position, Activity.milestone_id)
        .where(Activity.project_id == project_id)
        .where(Activity.deleted_at.is_(None))
    )
    acts_by_milestone: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for aid, pos, mid in db.execute(a_stmt).all():
        acts_by_milestone[mid].append((aid, pos))
    a_id_to_rank: Dict[str, Tuple[int, int]] = {}
    for mid, pairs in acts_by_milestone.items():
        m_rank = m_id_to_rank.get(mid)
        if m_rank is None:
            continue  # orphan (parent milestone soft-deleted)
        pairs.sort(key=lambda x: (x[1], x[0]))
        for a_idx, (aid, _pos) in enumerate(pairs, start=1):
            idx.activity_id_to_label[aid] = f"A{m_rank}.{a_idx}"
            a_id_to_rank[aid] = (m_rank, a_idx)

    # ---- Tasks ----------------------------------------------------------
    t_stmt = (
        select(Task.id, Task.position, Task.activity_id)
        .where(Task.project_id == project_id)
        .where(Task.deleted_at.is_(None))
    )
    tasks_by_activity: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for tid, pos, aid in db.execute(t_stmt).all():
        tasks_by_activity[aid].append((tid, pos))
    t_id_to_rank: Dict[str, Tuple[int, int, int]] = {}
    for aid, pairs in tasks_by_activity.items():
        m_a = a_id_to_rank.get(aid)
        if m_a is None:
            continue
        m_rank, a_rank = m_a
        pairs.sort(key=lambda x: (x[1], x[0]))
        for t_idx, (tid, _pos) in enumerate(pairs, start=1):
            idx.task_id_to_label[tid] = f"T{m_rank}.{a_rank}.{t_idx}"
            t_id_to_rank[tid] = (m_rank, a_rank, t_idx)

    # ---- Subtasks (Doc 24 variable-depth) -------------------------------
    s_stmt = (
        select(
            Subtask.id,
            Subtask.position,
            Subtask.task_id,
            Subtask.parent_subtask_id,
        )
        .where(Subtask.project_id == project_id)
        .where(Subtask.deleted_at.is_(None))
    )
    top_by_task: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    children_by_parent: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for sid, pos, tid, pid in db.execute(s_stmt).all():
        if pid is None:
            top_by_task[tid].append((sid, pos))
        else:
            children_by_parent[pid].append((sid, pos))
    for bucket in top_by_task.values():
        bucket.sort(key=lambda x: (x[1], x[0]))
    for bucket in children_by_parent.values():
        bucket.sort(key=lambda x: (x[1], x[0]))

    # DFS per top-level subtask, building the rank suffix as we descend.
    for tid, top_pairs in top_by_task.items():
        m_a_t = t_id_to_rank.get(tid)
        if m_a_t is None:
            continue
        m_rank, a_rank, t_rank = m_a_t
        prefix = f"S{m_rank}.{a_rank}.{t_rank}"
        for top_idx, (top_sid, _pos) in enumerate(top_pairs, start=1):
            stack: List[Tuple[str, str]] = [(top_sid, f"{prefix}.{top_idx}")]
            while stack:
                node_id, label = stack.pop()
                idx.subtask_id_to_label[node_id] = label
                children = children_by_parent.get(node_id, [])
                for child_idx, (child_sid, _cpos) in enumerate(
                    children, start=1,
                ):
                    stack.append((child_sid, f"{label}.{child_idx}"))

    return idx


# =========================================================================
# Assignee display-name lookup (inline port of monolith's bulk helper)
# =========================================================================

def _bulk_user_name_lookup(
    db: Session, user_ids: List[Optional[str]],
) -> Dict[str, str]:
    """``{user_id: display_name}`` for the given UUIDs. Single query.

    Soft-deleted users still resolve so legacy rows don't surface NULL
    names. The validator blocks new assignments to deleted users at
    write time.
    """
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    out: Dict[str, str] = {}
    stmt = (
        select(
            MirrorUser.id,
            MirrorUser.first_name,
            MirrorUser.last_name,
            MirrorUser.login,
        )
        .where(MirrorUser.id.in_(ids))
    )
    for uid, fn, ln, login in db.execute(stmt).all():
        fn = (fn or "").strip()
        ln = (ln or "").strip()
        if fn and ln:
            out[uid] = f"{fn} {ln}"
        elif fn:
            out[uid] = fn
        elif ln:
            out[uid] = ln
        else:
            out[uid] = login
    return out


# =========================================================================
# TreeService
# =========================================================================

class TreeService:
    """One method — ``get_project_tree`` — returns the full M/A/T/S
    payload for one project. Keeps a session reference for the seven
    table reads + the dep/label/assignee lookups."""

    def __init__(self, db: Session):
        self.db = db

    def get_project_tree(
        self,
        project_id: str,
        *,
        include_deleted: bool = False,
    ) -> Dict[str, Any]:
        db = self.db

        project = db.execute(
            select(Project).where(Project.id == project_id)
        ).scalar_one_or_none()
        if project is None:
            raise NotFoundError("The project could not be found.")
        if not include_deleted and project.deleted_at is not None:
            # Monolith parity: soft-deleted branch uses the VERBOSE form
            # (distinct from the missing-row form just above). Quoting the
            # UUID explicitly tells the FE "this row exists in the DB but
            # is gone" — useful for restore flows.
            raise NotFoundError(
                f"Project with ID {project_id} has been deleted",
            )

        # Single "today" reference for the entire tree — sampled once so
        # every node gets a consistent verdict even on a slow request
        # that straddles IST midnight.
        today_ist: _date_type = datetime.now(IST).date()

        # All queries filter by the denormalized project_id (one index
        # per table). The local helper applies the soft-delete filter
        # unless the caller asked to include deleted rows.
        def _scoped(stmt, model):
            stmt = stmt.where(model.project_id == project_id)
            if not include_deleted:
                stmt = stmt.where(model.deleted_at.is_(None))
            return stmt

        milestones = list(
            db.execute(
                _scoped(select(Milestone), Milestone)
                .order_by(Milestone.position.asc(), Milestone.id.asc())
            ).scalars().all()
        )
        activities = list(
            db.execute(
                _scoped(select(Activity), Activity)
                .order_by(Activity.position.asc(), Activity.id.asc())
            ).scalars().all()
        )
        act_resources = list(
            db.execute(_scoped(select(ActivityResource), ActivityResource))
            .scalars().all()
        )

        # One-shot vendor lookup so each activity node emits ``vendorName``
        # alongside ``vendorId`` — the FE consumes the tree for dependency
        # graphs and was forced to do a per-vendorId round-trip before
        # this lookup landed in the monolith.
        vendor_ids: set = {a.vendor_id for a in activities if a.vendor_id}
        vendor_name_by_id: Dict[str, str] = {}
        if vendor_ids:
            v_stmt = (
                select(Vendor.id, Vendor.name)
                .where(Vendor.id.in_(vendor_ids))
            )
            for vid, vname in db.execute(v_stmt).all():
                vendor_name_by_id[vid] = vname

        tasks = list(
            db.execute(
                _scoped(select(Task), Task)
                .order_by(Task.position.asc(), Task.id.asc())
            ).scalars().all()
        )
        task_resources = list(
            db.execute(_scoped(select(TaskResource), TaskResource))
            .scalars().all()
        )
        subtasks = list(
            db.execute(
                _scoped(select(Subtask), Subtask)
                .order_by(Subtask.position.asc(), Subtask.id.asc())
            ).scalars().all()
        )
        sub_resources = list(
            db.execute(_scoped(select(SubtaskResource), SubtaskResource))
            .scalars().all()
        )

        # Bulk-resolve assignee display names across all tasks + subtasks
        # in a single users-table read.
        assignee_uids: List[Optional[str]] = (
            [getattr(t, "assigned_to", None) for t in tasks]
            + [getattr(s, "assigned_to", None) for s in subtasks]
        )
        assignee_name_by_id: Dict[str, str] = _bulk_user_name_lookup(
            db, assignee_uids,
        )

        # Bulk-load dependency edges (4 queries — one per association
        # table). Store as ``{source_id: [target_id, ...]}`` so each
        # node render is O(1). Project-svc dependency tables don't carry
        # project_id or deleted_at, so we narrow by joining against the
        # live M/A/T/S id sets we already loaded.
        live_m_ids = {m.id for m in milestones}
        live_a_ids = {a.id for a in activities}
        live_t_ids = {t.id for t in tasks}
        live_s_ids = {s.id for s in subtasks}

        milestone_deps_by_source: Dict[str, List[str]] = defaultdict(list)
        if live_m_ids:
            md_stmt = select(
                MilestoneDependency.from_milestone_id,
                MilestoneDependency.to_milestone_id,
            ).where(MilestoneDependency.from_milestone_id.in_(live_m_ids))
            for src, tgt in db.execute(md_stmt).all():
                if tgt in live_m_ids:
                    milestone_deps_by_source[src].append(tgt)

        act_deps_by_source: Dict[str, List[str]] = defaultdict(list)
        if live_a_ids:
            ad_stmt = select(
                ActivityDependency.from_activity_id,
                ActivityDependency.to_activity_id,
            ).where(ActivityDependency.from_activity_id.in_(live_a_ids))
            for src, tgt in db.execute(ad_stmt).all():
                if tgt in live_a_ids:
                    act_deps_by_source[src].append(tgt)

        task_deps_by_source: Dict[str, List[str]] = defaultdict(list)
        if live_t_ids:
            td_stmt = select(
                TaskDependency.from_task_id,
                TaskDependency.to_task_id,
            ).where(TaskDependency.from_task_id.in_(live_t_ids))
            for src, tgt in db.execute(td_stmt).all():
                if tgt in live_t_ids:
                    task_deps_by_source[src].append(tgt)

        subtask_deps_by_source: Dict[str, List[str]] = defaultdict(list)
        if live_s_ids:
            sd_stmt = select(
                SubtaskDependency.from_subtask_id,
                SubtaskDependency.to_subtask_id,
            ).where(SubtaskDependency.from_subtask_id.in_(live_s_ids))
            for src, tgt in db.execute(sd_stmt).all():
                if tgt in live_s_ids:
                    subtask_deps_by_source[src].append(tgt)

        # Build the label index ONCE per tree request — populates
        # displayCode + dependsOnDisplay on every node.
        label_idx = _build_label_index(db, project_id)

        # Group children by their immediate parent for O(1) lookup during
        # stitch.
        acts_by_milestone: Dict[str, List[Any]] = defaultdict(list)
        for a in activities:
            acts_by_milestone[a.milestone_id].append(a)

        ar_by_act: Dict[str, Any] = {r.activity_id: r for r in act_resources}

        tasks_by_activity: Dict[str, List[Any]] = defaultdict(list)
        for t in tasks:
            tasks_by_activity[t.activity_id].append(t)

        tr_by_task: Dict[str, Any] = {r.task_id: r for r in task_resources}

        # Doc 24: subtasks can nest. Group top-level under their root
        # task, and every other subtask under its immediate parent
        # subtask.
        top_subs_by_task: Dict[str, List[Any]] = defaultdict(list)
        children_by_parent_sub: Dict[str, List[Any]] = defaultdict(list)
        for s in subtasks:
            if getattr(s, "parent_subtask_id", None) is None:
                top_subs_by_task[s.task_id].append(s)
            else:
                children_by_parent_sub[s.parent_subtask_id].append(s)

        sr_by_sub: Dict[str, Any] = {r.subtask_id: r for r in sub_resources}

        # ---- Stitch bottom-up ------------------------------------------
        def subtask_node(s: Any) -> Dict[str, Any]:
            # Resource row exists only in details mode; count mode uses
            # ``resource_count``.
            resource = (
                sr_by_sub.get(s.id)
                if getattr(s, "type", None) == "resource"
                and getattr(s, "resource_mode", None) == "details"
                else None
            )
            deps = sorted(subtask_deps_by_source.get(s.id, []))
            payload = {
                "id": s.id,
                "displayCode": label_idx.label_of(KIND_SUBTASK, s.id),
                "taskId": s.task_id,
                "projectId": s.project_id,
                "parentSubtaskId": getattr(s, "parent_subtask_id", None),
                "name": s.name,
                "description": s.description,
                "type": getattr(s, "type", None),
                "status": getattr(s, "status", None),
                "priority": getattr(s, "priority", None),
                "assignedTo": getattr(s, "assigned_to", None),
                "assignedToName": assignee_name_by_id.get(
                    getattr(s, "assigned_to", None),
                ),
                "startDate": iso_ist(s.start_date),
                "endDate": iso_ist(s.end_date),
                "actualStartDate": iso_ist(s.actual_start_date),
                "actualEndDate": iso_ist(s.actual_end_date),
                "position": s.position,
                "resourceMode": getattr(s, "resource_mode", None),
                "resourceCount": getattr(s, "resource_count", None),
                "dependsOn": deps,
                "dependsOnDisplay": label_idx.labels_of(KIND_SUBTASK, deps),
                "deletedAt": iso_ist(s.deleted_at),
                "resource": _resource_payload(resource) if resource else None,
                "subtasks": [
                    subtask_node(child)
                    for child in children_by_parent_sub.get(s.id, [])
                ],
            }
            return _attach_schedule_status(
                payload, s.start_date, s.end_date, today_ist,
                actual_start_date=getattr(s, "actual_start_date", None),
                actual_end_date=getattr(s, "actual_end_date", None),
            )

        def task_node(t: Any) -> Dict[str, Any]:
            resource = (
                tr_by_task.get(t.id)
                if getattr(t, "type", None) == "resource"
                and getattr(t, "resource_mode", None) == "details"
                else None
            )
            deps = sorted(task_deps_by_source.get(t.id, []))
            payload = {
                "id": t.id,
                "displayCode": label_idx.label_of(KIND_TASK, t.id),
                "activityId": t.activity_id,
                "projectId": t.project_id,
                "name": t.name,
                "description": t.description,
                "type": getattr(t, "type", None),
                "status": getattr(t, "status", None),
                "priority": getattr(t, "priority", None),
                "assignedTo": getattr(t, "assigned_to", None),
                "assignedToName": assignee_name_by_id.get(
                    getattr(t, "assigned_to", None),
                ),
                "startDate": iso_ist(t.start_date),
                "endDate": iso_ist(t.end_date),
                "actualStartDate": iso_ist(t.actual_start_date),
                "actualEndDate": iso_ist(t.actual_end_date),
                "position": t.position,
                "resourceMode": getattr(t, "resource_mode", None),
                "resourceCount": getattr(t, "resource_count", None),
                "dependsOn": deps,
                "dependsOnDisplay": label_idx.labels_of(KIND_TASK, deps),
                "deletedAt": iso_ist(t.deleted_at),
                "resource": _resource_payload(resource) if resource else None,
                "subtasks": [
                    subtask_node(s) for s in top_subs_by_task.get(t.id, [])
                ],
            }
            return _attach_schedule_status(
                payload, t.start_date, t.end_date, today_ist,
                actual_start_date=getattr(t, "actual_start_date", None),
                actual_end_date=getattr(t, "actual_end_date", None),
            )

        def activity_node(a: Any) -> Dict[str, Any]:
            resource = (
                ar_by_act.get(a.id)
                if getattr(a, "type", None) == "resource"
                and getattr(a, "resource_mode", None) == "details"
                else None
            )
            deps = sorted(act_deps_by_source.get(a.id, []))
            payload = {
                "id": a.id,
                "displayCode": label_idx.label_of(KIND_ACTIVITY, a.id),
                "milestoneId": a.milestone_id,
                "projectId": a.project_id,
                "name": a.name,
                "description": a.description,
                "type": getattr(a, "type", None),
                "status": getattr(a, "status", None),
                # Doc 39 ownership fields.
                "ownerDivision": getattr(a, "owner_division", None),
                "concernedDivision": getattr(a, "concerned_divisions", None) or [],
                "vendorId": getattr(a, "vendor_id", None),
                "vendorName": vendor_name_by_id.get(getattr(a, "vendor_id", None)),
                "priority": getattr(a, "priority", None),
                "startDate": iso_ist(a.start_date),
                "endDate": iso_ist(a.end_date),
                "actualStartDate": iso_ist(a.actual_start_date),
                "actualEndDate": iso_ist(a.actual_end_date),
                "position": a.position,
                "resourceMode": getattr(a, "resource_mode", None),
                "resourceCount": getattr(a, "resource_count", None),
                "dependsOn": deps,
                "dependsOnDisplay": label_idx.labels_of(KIND_ACTIVITY, deps),
                "deletedAt": iso_ist(a.deleted_at),
                "resource": _resource_payload(resource) if resource else None,
                "tasks": [task_node(t) for t in tasks_by_activity.get(a.id, [])],
            }
            return _attach_schedule_status(
                payload, a.start_date, a.end_date, today_ist,
                actual_start_date=getattr(a, "actual_start_date", None),
                actual_end_date=getattr(a, "actual_end_date", None),
            )

        def milestone_node(m: Any) -> Dict[str, Any]:
            deps = sorted(milestone_deps_by_source.get(m.id, []))
            payload = {
                "id": m.id,
                "displayCode": label_idx.label_of(KIND_MILESTONE, m.id),
                "projectId": m.project_id,
                "name": m.name,
                "description": m.description,
                "startDate": iso_ist(m.start_date),
                "endDate": iso_ist(m.end_date),
                "actualStartDate": iso_ist(getattr(m, "actual_start_date", None)),
                "actualEndDate": iso_ist(getattr(m, "actual_end_date", None)),
                "position": m.position,
                "status": getattr(m, "status", None),
                "priority": getattr(m, "priority", None),
                "dependsOn": deps,
                "dependsOnDisplay": label_idx.labels_of(KIND_MILESTONE, deps),
                "deletedAt": iso_ist(m.deleted_at),
                "activities": [
                    activity_node(a) for a in acts_by_milestone.get(m.id, [])
                ],
            }
            return _attach_schedule_status(
                payload, m.start_date, m.end_date, today_ist,
                actual_start_date=getattr(m, "actual_start_date", None),
                actual_end_date=getattr(m, "actual_end_date", None),
            )

        tree_milestones = [milestone_node(m) for m in milestones]

        # Small counts block for observability — useful for UI and tests.
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
        pid = project.id
        return {
            "_type": "ProjectTree",
            "_links": {
                "self": {
                    "href": (
                        f"/project/projects/{pid}/tree" if pid else None
                    ),
                },
                "project": {
                    "href": (
                        f"/project/projects/{pid}" if pid else None
                    ),
                },
            },
            "project": {
                "id": pid,
                "projectCode": getattr(project, "project_code", None),
                "name": getattr(project, "name", None),
                "description": getattr(project, "description", None),
                "status": getattr(project, "status", None),
                "owner": getattr(project, "owner", None),
                "category": getattr(project, "category", None),
                "startDate": iso_ist(getattr(project, "start_date", None)),
                "endDate": iso_ist(getattr(project, "end_date", None)),
                "isPublic": getattr(project, "public", None),
            },
            "counts": counts,
            "milestones": tree_milestones,
        }
