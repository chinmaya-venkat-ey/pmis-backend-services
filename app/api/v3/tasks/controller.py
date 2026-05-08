"""Tasks controller."""
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
    KIND_TASK,
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

from .schemas import TaskCreateRequest, TaskUpdateRequest, TaskListQuery
from .services import (
    create_task, get_task_with_resource, list_tasks,
    update_task, delete_task, restore_task,
)


# Doc 30 form-field spec. Tasks accept the same shape as activities
# minus the type discriminator — type is inherited from the parent
# activity. ``resourceMode`` / ``resourceCount`` / ``resource`` are
# only meaningful when the parent's type is 'resource'; the service
# layer rejects them otherwise.
_TASK_REQUIRED_STRING_KEYS = ("name",)
_TASK_OPTIONAL_STRING_KEYS = (
    "description", "startDate", "endDate", "actualStartDate", "actualEndDate",
    "resourceMode", "assignedTo",
)
_TASK_INT_KEYS = ("position", "resourceCount")
_TASK_ARRAY_KEYS = ("dependsOn",)
_TASK_OBJECT_KEYS = ("resource",)


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
    t: Dict[str, Any],
    resource: Optional[Dict[str, Any]] = None,
    label_index: Optional[LabelIndex] = None,
    base_url: str = "/api/v3",
    *,
    assigned_to_name: Optional[str] = None,
) -> Dict[str, Any]:
    deps = t.get("depends_on") or []
    display_code = (
        label_index.label_of(KIND_TASK, t["id"]) if label_index else None
    )
    deps_display = (
        label_index.labels_of(KIND_TASK, deps) if label_index else []
    )
    return {
        "_type": "Task",
        "_links": {
            "self": {"href": f"{base_url}/tasks/{t['id']}", "title": t["name"]},
            "activity": {"href": f"{base_url}/activities/{t['activity_id']}"},
            "project": {"href": f"{base_url}/projects/{t['project_id']}"},
        },
        "id": t["id"],
        "displayCode": display_code,
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
        "status": t.get("status"),
        # Doc 41 follow-up: optional single assignee. ``assignedTo`` is
        # the user UUID; ``assignedToName`` is the resolved display name
        # (caller-supplied via the kwarg). Both NULL when unassigned.
        "assignedTo": t.get("assigned_to"),
        "assignedToName": assigned_to_name,
        "dependsOn": deps,
        "dependsOnDisplay": deps_display,
        "createdAt": t["created_at"],
        "updatedAt": t["updated_at"],
        "createdBy": t["created_by"],
        "updatedBy": t["updated_by"],
        "deletedAt": t["deleted_at"],
        "resource": _format_resource(resource),
    }


def _resolve_assignee_name(db: Session, user_id: Optional[str]) -> Optional[str]:
    """Single-user name lookup for the response. NULL when unassigned."""
    if not user_id:
        return None
    from ....shared.assignee import bulk_user_name_lookup
    return bulk_user_name_lookup(db, [user_id]).get(user_id)


class TaskController:
    @staticmethod
    def create(request: Request, activity_id: str, data: TaskCreateRequest, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        # Doc 38: TaskCreateRequest is trimmed to name/desc/dates only.
        # Status / dependsOn / resource* / actual dates / position move
        # to PATCH.
        t, r = create_task(
            db,
            activity_id=activity_id,
            name=data.name, description=data.description,
            start_date=data.start_date, end_date=data.end_date,
            actual_start_date=data.actual_start_date,
            actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode=None, resource_count=None,
            resource=None, current_user_id=cuid,
            depends_on=data.depends_on,
            status=data.status,
            assigned_to=data.assigned_to,
        )
        idx = build_label_index_for_project(db, t.project_id)
        return BaseController.created(data=format_task_response(
            t.to_dict(), r.to_dict() if r else None, label_index=idx,
            assigned_to_name=_resolve_assignee_name(db, t.assigned_to),
        ))

    @staticmethod
    async def create_multipart(
        request: Request, activity_id: str, db: Session,
    ) -> JSONResponse:
        """Doc 30: create a task PLUS optional inline comment / files.

        Multipart form mirrors the JSON body 1:1 (same field names);
        ``dependsOn`` is JSON-encoded; ``resource`` (when the parent
        activity is type='resource' in details mode) is JSON-encoded
        as an object string. Plus the comment/file fields:
          * ``body``  — optional comment text
          * ``files`` — optional repeatable file uploads
        """
        form = await request.form()

        # ---- 1. Parse + Pydantic-validate task fields -------------------
        try:
            fields = parse_form_fields(
                form,
                required_string_keys=_TASK_REQUIRED_STRING_KEYS,
                string_keys=_TASK_OPTIONAL_STRING_KEYS,
                int_keys=_TASK_INT_KEYS,
                array_keys=_TASK_ARRAY_KEYS,
                object_keys=_TASK_OBJECT_KEYS,
            )
        except Multipart422 as e:
            return BaseController.error(
                format_error_response(
                    error_type="validation_error",
                    message="Invalid task form fields.",
                    details={"errors": e.detail},
                ),
                status=422,
            )
        try:
            data = TaskCreateRequest.model_validate(fields)
        except ValidationError as e:
            return BaseController.error(
                format_error_response(
                    error_type="validation_error",
                    message="Task field validation failed.",
                    details={"errors": sanitize_pydantic_errors(e.errors())},
                ),
                status=422,
            )

        body = form.get("body") or ""
        if not isinstance(body, str):
            body = ""
        files = extract_files_from_form(form)

        # ---- 1b. Pre-validate files BEFORE the task is inserted. --------
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

        # ---- 2. Create task --------------------------------------------
        cuid = getattr(request.state, "user_id", None)
        # Doc 38: trimmed to name/desc/dates on create.
        t, r = create_task(
            db,
            activity_id=activity_id,
            name=data.name, description=data.description,
            start_date=data.start_date, end_date=data.end_date,
            actual_start_date=data.actual_start_date,
            actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode=None, resource_count=None,
            resource=None, current_user_id=cuid,
            depends_on=data.depends_on,
            status=data.status,
            assigned_to=data.assigned_to,
        )

        # ---- 3. Inline comment / standalone attachments ----------------
        comment_payload, standalone_payload, err_tuple = persist_inline_comment_or_files(
            db,
            target_kind="task",
            target_id=t.id,
            body=body,
            files=files,
            current_user_id=cuid,
            format_comment_response=format_comment_response,
            format_attachment_response=format_attachment_response,
            parent_label="Task",
            retry_endpoint_path=f"POST /api/v3/tasks/{t.id}/comments",
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

        # ---- 4. Build response -----------------------------------------
        idx = build_label_index_for_project(db, t.project_id)
        response_data = format_task_response(
            t.to_dict(), r.to_dict() if r else None, label_index=idx,
            assigned_to_name=_resolve_assignee_name(db, t.assigned_to),
        )
        if comment_payload is not None:
            response_data["comment"] = comment_payload
        if standalone_payload:
            response_data["standaloneAttachments"] = standalone_payload
        return BaseController.created(data=response_data)

    @staticmethod
    def list(request: Request, activity_id: str, query: TaskListQuery, db: Session) -> JSONResponse:
        paged = list_tasks(db, activity_id=activity_id, page=query.offset, page_size=query.pageSize, include_deleted=query.includeDeleted)
        items_data = list(paged.items)
        idx = (
            build_label_index_for_project(db, items_data[0].project_id)
            if items_data else None
        )
        # Doc 41 follow-up: bulk-resolve assignee names for the page.
        from ....shared.assignee import bulk_user_name_lookup
        name_by_uid = bulk_user_name_lookup(
            db, (t.assigned_to for t in items_data if t.assigned_to),
        )
        items = [
            format_task_response(
                t.to_dict(), None, label_index=idx,
                assigned_to_name=name_by_uid.get(t.assigned_to),
            )
            for t in items_data
        ]
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
        idx = build_label_index_for_project(db, t.project_id)
        return BaseController.ok(data=format_task_response(
            t.to_dict(), r.to_dict() if r else None, label_index=idx,
            assigned_to_name=_resolve_assignee_name(db, t.assigned_to),
        ))

    @staticmethod
    def update(request: Request, task_id: str, data: TaskUpdateRequest, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        # Doc 38: type / resource_mode / resource_count / resource dropped
        # from the wire. Pass None into the underlying service.
        # Doc 41 follow-up: PATCH ``assignedTo`` distinguishes omitted
        # (no change) from null (unassign). Forward only when present.
        update_kwargs = dict(
            task_id=task_id,
            name=data.name, description=data.description, type=None,
            start_date=data.start_date, end_date=data.end_date,
            actual_start_date=data.actual_start_date, actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode=None, resource_count=None,
            resource=None, current_user_id=cuid,
            depends_on=data.depends_on,
            status=data.status,
        )
        if "assigned_to" in data.model_fields_set:
            update_kwargs["assigned_to"] = data.assigned_to
        t, r = update_task(db, **update_kwargs)
        idx = build_label_index_for_project(db, t.project_id)
        return BaseController.ok(data=format_task_response(
            t.to_dict(), r.to_dict() if r else None, label_index=idx,
            assigned_to_name=_resolve_assignee_name(db, t.assigned_to),
        ))

    @staticmethod
    def delete(request: Request, task_id: str, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        delete_task(db, task_id=task_id, current_user_id=cuid)
        return BaseController.no_content()

    @staticmethod
    def restore(request: Request, task_id: str, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        t = restore_task(db, task_id=task_id, current_user_id=cuid)
        idx = build_label_index_for_project(db, t.project_id)
        return BaseController.ok(data=format_task_response(
            t.to_dict(), label_index=idx,
            assigned_to_name=_resolve_assignee_name(db, t.assigned_to),
        ))
