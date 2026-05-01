"""
Project tree aggregator.

One SELECT per table keyed on the denormalized project_id, then stitched
together in Python via dicts. 7 queries total (milestones, activities,
activity_resources, tasks, task_resources, subtasks, subtask_resources).

Returns a dict ready to serialize via api_response envelope.
"""
from typing import Any, Dict, List, Optional
from collections import defaultdict

from sqlalchemy.orm import Session

from ....core.errors import NotFoundError
from ....infrastructure.db.models.project import ProjectModel
from ....infrastructure.db.models.milestone import MilestoneModel
from ....infrastructure.db.models.activity import ActivityModel
from ....infrastructure.db.models.activity_dependency import ActivityDependencyModel
from ....infrastructure.db.models.activity_resource import ActivityResourceModel
from ....infrastructure.db.models.task import TaskModel
from ....infrastructure.db.models.task_dependency import TaskDependencyModel
from ....infrastructure.db.models.task_resource import TaskResourceModel
from ....infrastructure.db.models.subtask import SubtaskModel
from ....infrastructure.db.models.subtask_dependency import SubtaskDependencyModel
from ....infrastructure.db.models.subtask_resource import SubtaskResourceModel


def _iso(v) -> Optional[str]:
    return v.isoformat() if v else None


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

    # All queries filter by the denormalized project_id (one index per table).
    def _q(model):
        q = db.query(model).filter(model.project_id == project_id)
        if not include_deleted:
            q = q.filter(model.deleted_at.is_(None))
        return q

    milestones = _q(MilestoneModel).order_by(MilestoneModel.position.asc(), MilestoneModel.id.asc()).all()
    activities = _q(ActivityModel).order_by(ActivityModel.position.asc(), ActivityModel.id.asc()).all()
    act_resources = _q(ActivityResourceModel).all()
    tasks = _q(TaskModel).order_by(TaskModel.position.asc(), TaskModel.id.asc()).all()
    task_resources = _q(TaskResourceModel).all()
    subtasks = _q(SubtaskModel).order_by(SubtaskModel.position.asc(), SubtaskModel.id.asc()).all()
    sub_resources = _q(SubtaskResourceModel).all()

    # Bulk-load dependency edges scoped to this project (3 queries — one per
    # association table). Store as dicts keyed by source id -> list of target
    # ids so each node render is O(1).
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

    subs_by_task: Dict[int, List[SubtaskModel]] = defaultdict(list)
    for s in subtasks:
        subs_by_task[s.task_id].append(s)

    sr_by_sub: Dict[int, SubtaskResourceModel] = {r.subtask_id: r for r in sub_resources}

    # --- Stitch bottom-up ---
    def subtask_node(s: SubtaskModel) -> Dict[str, Any]:
        # Resource row exists only in details mode; count mode uses resource_count.
        resource = (
            sr_by_sub.get(s.id)
            if s.type == "resource" and getattr(s, "resource_mode", None) == "details"
            else None
        )
        return {
            "id": s.id, "taskId": s.task_id, "projectId": s.project_id,
            "name": s.name, "description": s.description, "type": s.type,
            "startDate": _iso(s.start_date), "endDate": _iso(s.end_date),
            "actualStartDate": _iso(s.actual_start_date),
            "actualEndDate": _iso(s.actual_end_date),
            "position": s.position,
            "resourceMode": getattr(s, "resource_mode", None),
            "resourceCount": getattr(s, "resource_count", None),
            "dependsOn": sorted(subtask_deps_by_source.get(s.id, [])),
            "deletedAt": _iso(s.deleted_at),
            "resource": _resource_payload(resource) if resource else None,
        }

    def task_node(t: TaskModel) -> Dict[str, Any]:
        resource = (
            tr_by_task.get(t.id)
            if t.type == "resource" and getattr(t, "resource_mode", None) == "details"
            else None
        )
        return {
            "id": t.id, "activityId": t.activity_id, "projectId": t.project_id,
            "name": t.name, "description": t.description, "type": t.type,
            "startDate": _iso(t.start_date), "endDate": _iso(t.end_date),
            "actualStartDate": _iso(t.actual_start_date),
            "actualEndDate": _iso(t.actual_end_date),
            "position": t.position,
            "resourceMode": getattr(t, "resource_mode", None),
            "resourceCount": getattr(t, "resource_count", None),
            "dependsOn": sorted(task_deps_by_source.get(t.id, [])),
            "deletedAt": _iso(t.deleted_at),
            "resource": _resource_payload(resource) if resource else None,
            "subtasks": [subtask_node(s) for s in subs_by_task.get(t.id, [])],
        }

    def activity_node(a: ActivityModel) -> Dict[str, Any]:
        resource = (
            ar_by_act.get(a.id)
            if a.type == "resource" and getattr(a, "resource_mode", None) == "details"
            else None
        )
        return {
            "id": a.id, "milestoneId": a.milestone_id, "projectId": a.project_id,
            "name": a.name, "description": a.description, "type": a.type,
            "status": getattr(a, "status", None),
            "startDate": _iso(a.start_date), "endDate": _iso(a.end_date),
            "actualStartDate": _iso(a.actual_start_date),
            "actualEndDate": _iso(a.actual_end_date),
            "position": a.position,
            "resourceMode": getattr(a, "resource_mode", None),
            "resourceCount": getattr(a, "resource_count", None),
            "dependsOn": sorted(act_deps_by_source.get(a.id, [])),
            "deletedAt": _iso(a.deleted_at),
            "resource": _resource_payload(resource) if resource else None,
            "tasks": [task_node(t) for t in tasks_by_activity.get(a.id, [])],
        }

    def milestone_node(m: MilestoneModel) -> Dict[str, Any]:
        return {
            "id": m.id, "projectId": m.project_id,
            "name": m.name, "description": m.description,
            "startDate": _iso(m.start_date), "endDate": _iso(m.end_date),
            "position": m.position,
            "deletedAt": _iso(m.deleted_at),
            "activities": [activity_node(a) for a in acts_by_milestone.get(m.id, [])],
        }

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
            "isVersion": getattr(project, "is_version", False),
            "baselineId": getattr(project, "baseline_id", None),
            "versionOf": getattr(project, "version_of", None),
            "versionNo": getattr(project, "version_no", 0),
        },
        "counts": counts,
        "milestones": tree_milestones,
    }
