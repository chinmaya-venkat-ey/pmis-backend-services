"""Activities controller."""
from typing import Any, Dict, Optional
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from .schemas import (
    ActivityCreateRequest,
    ActivityUpdateRequest,
    ActivityListQuery,
    ResourceCountActivityCreateRequest,
    ResourceDetailsActivityCreateRequest,
    StandardActivityCreateRequest,
    TransactionalActivityCreateRequest,
)
from .services import (
    create_activity, get_activity_with_resource, list_activities,
    update_activity, delete_activity, restore_activity,
)


def _format_resource(r: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    return {
        "_type": "ActivityResource",
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
        "typeOfResourceId": r.get("type_of_resource_id"),
        "division": r.get("division"),
        "divisionOther": r.get("division_other"),
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
    }


def format_activity_response(
    a: Dict[str, Any], resource: Optional[Dict[str, Any]] = None, base_url: str = "/api/v3",
) -> Dict[str, Any]:
    return {
        "_type": "Activity",
        "_links": {
            "self": {"href": f"{base_url}/activities/{a['id']}", "title": a["name"]},
            "milestone": {"href": f"{base_url}/milestones/{a['milestone_id']}"},
            "project": {"href": f"{base_url}/projects/{a['project_id']}"},
        },
        "id": a["id"],
        "projectId": a["project_id"],
        "milestoneId": a["milestone_id"],
        "name": a["name"],
        "description": a["description"],
        "type": a["type"],
        "startDate": a["start_date"],
        "endDate": a["end_date"],
        "actualStartDate": a["actual_start_date"],
        "actualEndDate": a["actual_end_date"],
        "position": a["position"],
        "resourceMode": a.get("resource_mode"),
        "resourceCount": a.get("resource_count"),
        "status": a.get("status"),
        "dependsOn": a.get("depends_on") or [],
        "createdAt": a["created_at"],
        "updatedAt": a["updated_at"],
        "createdBy": a["created_by"],
        "updatedBy": a["updated_by"],
        "deletedAt": a["deleted_at"],
        "resource": _format_resource(resource),
    }


class ActivityController:
    @staticmethod
    def create(request: Request, milestone_id: str, data: ActivityCreateRequest, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        resource_dict = data.resource.model_dump() if data.resource else None
        activity, resource = create_activity(
            db,
            milestone_id=milestone_id,
            name=data.name,
            description=data.description,
            type=data.type,
            start_date=data.start_date,
            end_date=data.end_date,
            actual_start_date=data.actual_start_date,
            actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode=data.resource_mode,
            resource_count=data.resource_count,
            resource=resource_dict,
            current_user_id=current_user_id,
            status=data.status,
            depends_on=data.depends_on,
        )
        return BaseController.created(data=format_activity_response(
            activity.to_dict(),
            resource.to_dict() if resource else None,
        ))

    # ------------------------------------------------------------------
    # Split-by-type create handlers.
    # Each one calls the single service with the right fixed type /
    # resource_mode arguments so the service layer (and its dependency-
    # graph, lineage propagation, audit) stay in one place.
    # ------------------------------------------------------------------

    @staticmethod
    def create_standard(
        request: Request,
        milestone_id: str,
        data: StandardActivityCreateRequest,
        db: Session,
    ) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        activity, resource = create_activity(
            db,
            milestone_id=milestone_id,
            name=data.name,
            description=data.description,
            type="standard",
            start_date=data.start_date,
            end_date=data.end_date,
            actual_start_date=data.actual_start_date,
            actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode=None,
            resource_count=None,
            resource=None,
            current_user_id=current_user_id,
            status=data.status,
            depends_on=data.depends_on,
        )
        return BaseController.created(data=format_activity_response(
            activity.to_dict(),
            resource.to_dict() if resource else None,
        ))

    @staticmethod
    def create_resource_count(
        request: Request,
        milestone_id: str,
        data: ResourceCountActivityCreateRequest,
        db: Session,
    ) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        activity, resource = create_activity(
            db,
            milestone_id=milestone_id,
            name=data.name,
            description=data.description,
            type="resource",
            start_date=data.start_date,
            end_date=data.end_date,
            actual_start_date=data.actual_start_date,
            actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode="count",
            resource_count=data.resource_count,
            resource=None,
            current_user_id=current_user_id,
            status=data.status,
            depends_on=data.depends_on,
        )
        return BaseController.created(data=format_activity_response(
            activity.to_dict(),
            resource.to_dict() if resource else None,
        ))

    @staticmethod
    def create_resource_details(
        request: Request,
        milestone_id: str,
        data: ResourceDetailsActivityCreateRequest,
        db: Session,
    ) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        activity, resource = create_activity(
            db,
            milestone_id=milestone_id,
            name=data.name,
            description=data.description,
            type="resource",
            start_date=data.start_date,
            end_date=data.end_date,
            actual_start_date=data.actual_start_date,
            actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode="details",
            resource_count=None,
            resource=data.resource.model_dump(),
            current_user_id=current_user_id,
            status=data.status,
            depends_on=data.depends_on,
        )
        return BaseController.created(data=format_activity_response(
            activity.to_dict(),
            resource.to_dict() if resource else None,
        ))

    @staticmethod
    def create_transactional(
        request: Request,
        milestone_id: str,
        data: TransactionalActivityCreateRequest,
        db: Session,
    ) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        activity, resource = create_activity(
            db,
            milestone_id=milestone_id,
            name=data.name,
            description=data.description,
            type="transactional",
            start_date=data.start_date,
            end_date=data.end_date,
            actual_start_date=data.actual_start_date,
            actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode=None,
            resource_count=None,
            resource=None,
            current_user_id=current_user_id,
            status=data.status,
            depends_on=data.depends_on,
        )
        return BaseController.created(data=format_activity_response(
            activity.to_dict(),
            resource.to_dict() if resource else None,
        ))

    @staticmethod
    def list(request: Request, milestone_id: str, query: ActivityListQuery, db: Session) -> JSONResponse:
        paged = list_activities(
            db, milestone_id=milestone_id,
            page=query.offset, page_size=query.pageSize,
            include_deleted=query.includeDeleted,
        )
        # Resource details are not inlined in the list; use GET /activities/{id} for that.
        items = [format_activity_response(a.to_dict(), None) for a in paged.items]
        payload = {
            "_type": "Collection",
            "_links": {"self": {"href": f"/api/v3/milestones/{milestone_id}/activities?offset={paged.page}&pageSize={paged.page_size}"}},
            "total": paged.total,
            "count": len(items),
            "pageSize": paged.page_size,
            "offset": paged.page,
            "_embedded": {"elements": items},
        }
        return BaseController.ok(data=payload)

    @staticmethod
    def get(request: Request, activity_id: str, db: Session) -> JSONResponse:
        activity, resource = get_activity_with_resource(db, activity_id)
        return BaseController.ok(data=format_activity_response(
            activity.to_dict(), resource.to_dict() if resource else None,
        ))

    @staticmethod
    def update(request: Request, activity_id: str, data: ActivityUpdateRequest, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        resource_dict = data.resource.model_dump() if data.resource else None
        activity, resource = update_activity(
            db,
            activity_id=activity_id,
            name=data.name,
            description=data.description,
            type=data.type,
            start_date=data.start_date,
            end_date=data.end_date,
            actual_start_date=data.actual_start_date,
            actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode=data.resource_mode,
            resource_count=data.resource_count,
            resource=resource_dict,
            current_user_id=current_user_id,
            status=data.status,
            depends_on=data.depends_on,
        )
        return BaseController.ok(data=format_activity_response(
            activity.to_dict(), resource.to_dict() if resource else None,
        ))

    @staticmethod
    def delete(request: Request, activity_id: str, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        delete_activity(db, activity_id=activity_id, current_user_id=current_user_id)
        return BaseController.no_content()

    @staticmethod
    def restore(request: Request, activity_id: str, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        activity = restore_activity(db, activity_id=activity_id, current_user_id=current_user_id)
        return BaseController.ok(data=format_activity_response(activity.to_dict()))
