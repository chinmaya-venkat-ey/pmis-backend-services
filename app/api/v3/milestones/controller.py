"""Milestones controller."""
from typing import Any, Dict
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.errors import NotFoundError
from ....core.response import format_collection_response
from ....infrastructure.db.repositories.project_repository import ProjectRepository
from .schemas import MilestoneCreateRequest, MilestoneUpdateRequest, MilestoneListQuery
from .services import (
    create_milestone, get_milestone, list_milestones,
    update_milestone, delete_milestone, restore_milestone,
)


def _verify_project_exists(db: Session, project_uuid: str) -> None:
    """Raises NotFoundError if no live project with this id (id is the UUID)."""
    if not ProjectRepository(db).exists_by_id(project_uuid):
        raise NotFoundError("The project could not be found.")


def format_milestone_response(m: dict, base_url: str = "/api/v3") -> Dict[str, Any]:
    return {
        "_type": "Milestone",
        "_links": {
            "self": {"href": f"{base_url}/milestones/{m['id']}", "title": m["name"]},
            "project": {"href": f"{base_url}/projects/{m['project_id']}"},
        },
        "id": m["id"],
        "projectId": m["project_id"],
        "name": m["name"],
        "description": m["description"],
        "startDate": m["start_date"],
        "endDate": m["end_date"],
        "position": m["position"],
        "status": m.get("status", "not_completed"),
        "depends": m.get("depends", []) or [],
        "vendors": m.get("vendors", []) or [],
        "createdAt": m["created_at"],
        "updatedAt": m["updated_at"],
        "createdBy": m["created_by"],
        "updatedBy": m["updated_by"],
        "deletedAt": m["deleted_at"],
    }


class MilestoneController:
    @staticmethod
    def create(request: Request, project_uuid: str, data: MilestoneCreateRequest, db: Session) -> JSONResponse:
        _verify_project_exists(db, project_uuid)
        project_id = project_uuid  # project_id IS the UUID
        current_user_id = getattr(request.state, "user_id", None)
        m = create_milestone(
            db,
            project_id=project_id,
            name=data.name,
            description=data.description,
            start_date=data.start_date,
            end_date=data.end_date,
            position=data.position,
            current_user_id=current_user_id,
            status=data.status,
            depends=data.depends,
            vendor_ids=data.vendors,
        )
        return BaseController.created(data=format_milestone_response(m.to_dict()))

    @staticmethod
    def list(request: Request, project_uuid: str, query: MilestoneListQuery, db: Session) -> JSONResponse:
        _verify_project_exists(db, project_uuid)
        project_id = project_uuid  # project_id IS the UUID
        paged = list_milestones(
            db, project_id=project_id,
            page=query.offset, page_size=query.pageSize,
            include_deleted=query.includeDeleted,
        )
        items = [format_milestone_response(m.to_dict()) for m in paged.items]
        payload = {
            "_type": "Collection",
            "_links": {"self": {"href": f"/api/v3/projects/{project_uuid}/milestones?offset={paged.page}&pageSize={paged.page_size}"}},
            "total": paged.total,
            "count": len(items),
            "pageSize": paged.page_size,
            "offset": paged.page,
            "_embedded": {"elements": items},
        }
        return BaseController.ok(data=payload)

    @staticmethod
    def get(request: Request, milestone_id: str, db: Session) -> JSONResponse:
        m = get_milestone(db, milestone_id)
        return BaseController.ok(data=format_milestone_response(m.to_dict()))

    @staticmethod
    def update(request: Request, milestone_id: str, data: MilestoneUpdateRequest, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        m = update_milestone(
            db,
            milestone_id=milestone_id,
            name=data.name,
            description=data.description,
            start_date=data.start_date,
            end_date=data.end_date,
            position=data.position,
            current_user_id=current_user_id,
            status=data.status,
            depends=data.depends,
            vendor_ids=data.vendors,
        )
        return BaseController.ok(data=format_milestone_response(m.to_dict()))

    @staticmethod
    def delete(request: Request, milestone_id: str, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        delete_milestone(db, milestone_id=milestone_id, current_user_id=current_user_id)
        return BaseController.no_content()

    @staticmethod
    def restore(request: Request, milestone_id: str, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        m = restore_milestone(db, milestone_id=milestone_id, current_user_id=current_user_id)
        return BaseController.ok(data=format_milestone_response(m.to_dict()))
