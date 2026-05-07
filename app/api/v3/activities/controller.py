"""Activities controller.

Doc 38: a single create handler covering both JSON and multipart inputs.
The four legacy type-specific handlers (create_standard /
create_resource_count / create_resource_details / create_transactional)
plus their multipart variants are replaced by ``create`` /
``create_multipart``.
"""
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.response import (
    format_attachment_response,
    format_comment_response,
    format_error_response,
)
from ....shared.labels import (
    KIND_ACTIVITY,
    LabelIndex,
    build_label_index_for_project,
)

# Doc 30: shared multipart machinery.
from .._inline_attachments import (
    Multipart422,
    extract_files_from_form,
    parse_form_fields,
    persist_inline_comment_or_files,
    pre_validate_files,
    sanitize_pydantic_errors,
)

from .schemas import ActivityCreateRequest, ActivityListQuery, ActivityUpdateRequest
from .services import (
    create_activity, get_activity_with_resource, list_activities,
    update_activity, delete_activity, restore_activity,
)


# Doc 38 multipart-form key spec.
# Doc 39: ownerDivision / vendorId are required on create; concernedDivision (list)
# is required as a list (multipart parses it from a repeated form field).
_ACTIVITY_REQUIRED_STRING_KEYS = ("name", "ownerDivision", "vendorId")
_ACTIVITY_OPTIONAL_STRING_KEYS = (
    "description", "startDate", "endDate",
)
_ACTIVITY_INT_KEYS = ("position",)
_ACTIVITY_ARRAY_KEYS = ("concernedDivision", "dependsOn")


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
    a: Dict[str, Any],
    resource: Optional[Dict[str, Any]] = None,
    label_index: Optional[LabelIndex] = None,
    base_url: str = "/api/v3",
) -> Dict[str, Any]:
    """HAL+JSON shape for one activity."""
    deps = a.get("depends_on") or []
    display_code = (
        label_index.label_of(KIND_ACTIVITY, a["id"]) if label_index else None
    )
    deps_display = (
        label_index.labels_of(KIND_ACTIVITY, deps) if label_index else []
    )
    return {
        "_type": "Activity",
        "_links": {
            "self": {"href": f"{base_url}/activities/{a['id']}", "title": a["name"]},
            "milestone": {"href": f"{base_url}/milestones/{a['milestone_id']}"},
            "project": {"href": f"{base_url}/projects/{a['project_id']}"},
        },
        "id": a["id"],
        "displayCode": display_code,
        "projectId": a["project_id"],
        "milestoneId": a["milestone_id"],
        "name": a["name"],
        "description": a["description"],
        # Doc 38: type / resource_* deprecated. Still surfaced for legacy rows.
        "type": a.get("type"),
        "ownerDivision": a.get("owner_division"),
        # Doc 39: ``concernedDivision`` keyword preserved on the wire for
        # FE compatibility; only the datatype changed from string to a
        # list of division codes. The legacy single ``concerned_division``
        # column is kept on disk but never surfaced through the API.
        "concernedDivision": a.get("concerned_divisions") or [],
        "vendorId": a.get("vendor_id"),
        "startDate": a["start_date"],
        "endDate": a["end_date"],
        "actualStartDate": a["actual_start_date"],
        "actualEndDate": a["actual_end_date"],
        "position": a["position"],
        "resourceMode": a.get("resource_mode"),
        "resourceCount": a.get("resource_count"),
        "status": a.get("status"),
        "dependsOn": deps,
        "dependsOnDisplay": deps_display,
        "createdAt": a["created_at"],
        "updatedAt": a["updated_at"],
        "createdBy": a["created_by"],
        "updatedBy": a["updated_by"],
        "deletedAt": a["deleted_at"],
        "resource": _format_resource(resource),
    }


async def _parse_and_validate_multipart_activity(request: Request):
    """Doc 38 multipart parser."""
    form = await request.form()
    try:
        fields = parse_form_fields(
            form,
            required_string_keys=_ACTIVITY_REQUIRED_STRING_KEYS,
            string_keys=_ACTIVITY_OPTIONAL_STRING_KEYS,
            int_keys=_ACTIVITY_INT_KEYS,
            array_keys=_ACTIVITY_ARRAY_KEYS,
            object_keys=(),
        )
    except Multipart422 as e:
        return BaseController.error(
            format_error_response(
                error_type="validation_error",
                message="Invalid activity form fields.",
                details={"errors": e.detail},
            ),
            status=422,
        ), None, None
    try:
        data = ActivityCreateRequest.model_validate(fields)
    except ValidationError as e:
        return BaseController.error(
            format_error_response(
                error_type="validation_error",
                message="Activity field validation failed.",
                details={"errors": sanitize_pydantic_errors(e.errors())},
            ),
            status=422,
        ), None, None
    body = form.get("body") or ""
    if not isinstance(body, str):
        body = ""
    files = extract_files_from_form(form)
    return data, body, files


def _persist_activity_inline(
    request: Request,
    db: Session,
    activity,
    body: str,
    files,
    *,
    activity_response: Dict[str, Any],
) -> JSONResponse:
    current_user_id = getattr(request.state, "user_id", None)
    comment_payload, standalone_payload, err_tuple = persist_inline_comment_or_files(
        db,
        target_kind="activity",
        target_id=activity.id,
        body=body,
        files=files,
        current_user_id=current_user_id,
        format_comment_response=format_comment_response,
        format_attachment_response=format_attachment_response,
        parent_label="Activity",
        retry_endpoint_path=f"POST /api/v3/activities/{activity.id}/comments",
    )
    if err_tuple is not None:
        err_dict, status = err_tuple
        return BaseController.error(
            format_error_response(
                error_type=err_dict["error_type"],
                message=err_dict["message"],
                details=err_dict["details"],
            ),
            status=status,
        )
    if comment_payload is not None:
        activity_response["comment"] = comment_payload
    if standalone_payload:
        activity_response["standaloneAttachments"] = standalone_payload
    return BaseController.created(data=activity_response)


class ActivityController:
    @staticmethod
    def create(
        request: Request,
        milestone_id: str,
        data: ActivityCreateRequest,
        db: Session,
    ) -> JSONResponse:
        """Doc 38: single create handler. No type/resource on create."""
        current_user_id = getattr(request.state, "user_id", None)
        activity, resource = create_activity(
            db,
            milestone_id=milestone_id,
            name=data.name,
            description=data.description,
            type=None,
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
            owner_division=data.owner_division,
            concerned_division=None,  # doc 39: legacy single column not written from create
            concerned_divisions=data.concerned_divisions,
            vendor_id=data.vendor_id,
        )
        idx = build_label_index_for_project(db, activity.project_id)
        return BaseController.created(data=format_activity_response(
            activity.to_dict(),
            resource.to_dict() if resource else None,
            label_index=idx,
        ))

    @staticmethod
    async def create_multipart(
        request: Request, milestone_id: str, db: Session,
    ) -> JSONResponse:
        result = await _parse_and_validate_multipart_activity(request)
        if isinstance(result[0], JSONResponse):
            return result[0]
        data, body, files = result
        file_err = pre_validate_files(files)
        if file_err is not None:
            return BaseController.error(
                format_error_response(
                    error_type=file_err["error_type"],
                    message=file_err["message"],
                    details=file_err["details"],
                ),
                status=422,
            )
        current_user_id = getattr(request.state, "user_id", None)
        activity, resource = create_activity(
            db,
            milestone_id=milestone_id,
            name=data.name,
            description=data.description,
            type=None,
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
            owner_division=data.owner_division,
            concerned_division=None,  # doc 39: legacy single column not written from create
            concerned_divisions=data.concerned_divisions,
            vendor_id=data.vendor_id,
        )
        idx = build_label_index_for_project(db, activity.project_id)
        response_data = format_activity_response(
            activity.to_dict(),
            resource.to_dict() if resource else None,
            label_index=idx,
        )
        return _persist_activity_inline(
            request, db, activity, body, files,
            activity_response=response_data,
        )

    @staticmethod
    def list(
        request: Request, milestone_id: str, query: ActivityListQuery, db: Session,
    ) -> JSONResponse:
        paged = list_activities(
            db, milestone_id=milestone_id,
            page=query.offset, page_size=query.pageSize,
            include_deleted=query.includeDeleted,
        )
        items_data = list(paged.items)
        idx = (
            build_label_index_for_project(db, items_data[0].project_id)
            if items_data else None
        )
        items = [
            format_activity_response(a.to_dict(), None, label_index=idx)
            for a in items_data
        ]
        payload = {
            "_type": "Collection",
            "_links": {
                "self": {
                    "href": (
                        f"/api/v3/milestones/{milestone_id}/activities"
                        f"?offset={paged.page}&pageSize={paged.page_size}"
                    ),
                },
            },
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
        idx = build_label_index_for_project(db, activity.project_id)
        return BaseController.ok(data=format_activity_response(
            activity.to_dict(),
            resource.to_dict() if resource else None,
            label_index=idx,
        ))

    @staticmethod
    def update(
        request: Request, activity_id: str, data: ActivityUpdateRequest, db: Session,
    ) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        # Doc 38: type / resource_mode / resource_count / resource are no
        # longer wire fields. Pass None so the underlying service (which
        # still accepts them as optional kwargs) doesn't try to flip them.
        activity, resource = update_activity(
            db,
            activity_id=activity_id,
            name=data.name,
            description=data.description,
            type=None,
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
            owner_division=data.owner_division,
            concerned_division=None,  # doc 39: legacy single column not written from create
            concerned_divisions=data.concerned_divisions,
            vendor_id=data.vendor_id,
        )
        idx = build_label_index_for_project(db, activity.project_id)
        return BaseController.ok(data=format_activity_response(
            activity.to_dict(),
            resource.to_dict() if resource else None,
            label_index=idx,
        ))

    @staticmethod
    def delete(request: Request, activity_id: str, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        delete_activity(db, activity_id=activity_id, current_user_id=current_user_id)
        return BaseController.no_content()

    @staticmethod
    def restore(request: Request, activity_id: str, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        activity = restore_activity(
            db, activity_id=activity_id, current_user_id=current_user_id,
        )
        idx = build_label_index_for_project(db, activity.project_id)
        return BaseController.ok(data=format_activity_response(
            activity.to_dict(), label_index=idx,
        ))
