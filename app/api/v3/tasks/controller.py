"""Tasks controller."""
from typing import Any, Dict, Optional
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from .schemas import TaskCreateRequest, TaskUpdateRequest, TaskListQuery
from .services import (
    create_task, get_task_with_resource, list_tasks,
    update_task, delete_task, restore_task,
)


def _format_resource(r: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    return {
        "_type": "TaskResource",
        "id": r["id"],
        "resourceName": r["resource_name"],
        "onboardDate": r["onboard_date"],
        "actualOnboardDate": r["actual_onboard_date"],
        "offboardDate": r["offboard_date"],
        "actualOffboardDate": r["actual_offboard_date"],
        "position": r["position"],
        "designation": r["designation"],
        "jobRole": r["job_role"],
        "qualification": r["qualification"],
        "experienceYears": r["experience_years"],
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
    }


def format_task_response(
    t: Dict[str, Any], resource: Optional[Dict[str, Any]] = None, base_url: str = "/api/v3",
) -> Dict[str, Any]:
    return {
        "_type": "Task",
        "_links": {
            "self": {"href": f"{base_url}/tasks/{t['id']}", "title": t["name"]},
            "activity": {"href": f"{base_url}/activities/{t['activity_id']}"},
            "project": {"href": f"{base_url}/projects/{t['project_id']}"},
        },
        "id": t["id"],
        "projectId": t["project_id"],
        "activityId": t["activity_id"],
        "name": t["name"],
        "description": t["description"],
        "type": t["type"],
        "startDate": t["start_date"],
        "endDate": t["end_date"],
        "actualStartDate": t["actual_start_date"],
        "actualEndDate": t["actual_end_date"],
        "position": t["position"],
        "resourceMode": t.get("resource_mode"),
        "resourceCount": t.get("resource_count"),
        "dependsOn": t.get("depends_on") or [],
        "createdAt": t["created_at"],
        "updatedAt": t["updated_at"],
        "createdBy": t["created_by"],
        "updatedBy": t["updated_by"],
        "deletedAt": t["deleted_at"],
        "resource": _format_resource(resource),
    }


class TaskController:
    @staticmethod
    def create(request: Request, activity_id: str, data: TaskCreateRequest, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        rd = data.resource.model_dump() if data.resource else None
        t, r = create_task(
            db,
            activity_id=activity_id,
            # ``type`` is no longer in the request body — the service derives
            # it from the parent activity. See task create service.
            name=data.name, description=data.description,
            start_date=data.start_date, end_date=data.end_date,
            actual_start_date=data.actual_start_date, actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode=data.resource_mode, resource_count=data.resource_count,
            resource=rd, current_user_id=cuid,
            depends_on=data.depends_on,
        )
        return BaseController.created(data=format_task_response(t.to_dict(), r.to_dict() if r else None))

    @staticmethod
    def list(request: Request, activity_id: str, query: TaskListQuery, db: Session) -> JSONResponse:
        paged = list_tasks(db, activity_id=activity_id, page=query.offset, page_size=query.pageSize, include_deleted=query.includeDeleted)
        items = [format_task_response(t.to_dict(), None) for t in paged.items]
        payload = {
            "_type": "Collection",
            "_links": {"self": {"href": f"/api/v3/activities/{activity_id}/tasks?offset={paged.page}&pageSize={paged.page_size}"}},
            "total": paged.total, "count": len(items),
            "pageSize": paged.page_size, "offset": paged.page,
            "_embedded": {"elements": items},
        }
        return BaseController.ok(data=payload)

    @staticmethod
    def get(request: Request, task_id: str, db: Session) -> JSONResponse:
        t, r = get_task_with_resource(db, task_id)
        return BaseController.ok(data=format_task_response(t.to_dict(), r.to_dict() if r else None))

    @staticmethod
    def update(request: Request, task_id: str, data: TaskUpdateRequest, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        rd = data.resource.model_dump() if data.resource else None
        t, r = update_task(
            db,
            task_id=task_id,
            name=data.name, description=data.description, type=data.type,
            start_date=data.start_date, end_date=data.end_date,
            actual_start_date=data.actual_start_date, actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode=data.resource_mode, resource_count=data.resource_count,
            resource=rd, current_user_id=cuid,
            depends_on=data.depends_on,
        )
        return BaseController.ok(data=format_task_response(t.to_dict(), r.to_dict() if r else None))

    @staticmethod
    def delete(request: Request, task_id: str, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        delete_task(db, task_id=task_id, current_user_id=cuid)
        return BaseController.no_content()

    @staticmethod
    def restore(request: Request, task_id: str, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        t = restore_task(db, task_id=task_id, current_user_id=cuid)
        return BaseController.ok(data=format_task_response(t.to_dict()))
