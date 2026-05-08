"""Subtasks controller."""
from collections import defaultdict
from typing import Any, Dict, List, Optional
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
    KIND_SUBTASK,
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

from .schemas import SubtaskCreateRequest, SubtaskUpdateRequest, SubtaskListQuery
from .services import (
    create_subtask, get_subtask_with_resource, list_subtasks,
    update_subtask, delete_subtask, restore_subtask,
)


# Doc 30 form-field spec — same shape as tasks; subtasks inherit type
# from the parent task (which inherits from the parent activity).
_SUBTASK_REQUIRED_STRING_KEYS = ("name",)
_SUBTASK_OPTIONAL_STRING_KEYS = (
    "description", "startDate", "endDate", "actualStartDate", "actualEndDate",
    "resourceMode", "assignedTo",
)
_SUBTASK_INT_KEYS = ("position", "resourceCount")
_SUBTASK_ARRAY_KEYS = ("dependsOn",)
_SUBTASK_OBJECT_KEYS = ("resource",)


async def _parse_and_validate_subtask_multipart(request: Request):
    """Doc 30: shared first-half for both subtask create variants.

    Returns ``(data, body, files)`` on success, or ``(JSONResponse, None,
    None)`` on parse / validation failure. Both task-scoped create and
    nested-under-subtask create use the same form schema (parents inject
    the right ``task_id`` / ``parent_subtask_id``).
    """
    form = await request.form()
    try:
        fields = parse_form_fields(
            form,
            required_string_keys=_SUBTASK_REQUIRED_STRING_KEYS,
            string_keys=_SUBTASK_OPTIONAL_STRING_KEYS,
            int_keys=_SUBTASK_INT_KEYS,
            array_keys=_SUBTASK_ARRAY_KEYS,
            object_keys=_SUBTASK_OBJECT_KEYS,
        )
    except Multipart422 as e:
        return (
            BaseController.error(
                format_error_response(
                    error_type="validation_error",
                    message="Invalid subtask form fields.",
                    details={"errors": e.detail},
                ),
                status=422,
            ),
            None, None,
        )
    try:
        data = SubtaskCreateRequest.model_validate(fields)
    except ValidationError as e:
        return (
            BaseController.error(
                format_error_response(
                    error_type="validation_error",
                    message="Subtask field validation failed.",
                    details={"errors": sanitize_pydantic_errors(e.errors())},
                ),
                status=422,
            ),
            None, None,
        )
    body = form.get("body") or ""
    if not isinstance(body, str):
        body = ""
    files = extract_files_from_form(form)
    return data, body, files


def _persist_subtask_inline(
    request: Request,
    db: Session,
    subtask,
    resource,
    body: str,
    files,
) -> JSONResponse:
    """Doc 30 third stage — route comment / standalone attachments and
    build response. Caller must have pre-validated files already."""
    cuid = getattr(request.state, "user_id", None)
    comment_payload, standalone_payload, err_tuple = persist_inline_comment_or_files(
        db,
        target_kind="subtask",
        target_id=subtask.id,
        body=body,
        files=files,
        current_user_id=cuid,
        format_comment_response=format_comment_response,
        format_attachment_response=format_attachment_response,
        parent_label="Subtask",
        retry_endpoint_path=f"POST /api/v3/subtasks/{subtask.id}/comments",
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
    idx = build_label_index_for_project(db, subtask.project_id)
    response_data = format_subtask_response(
        subtask.to_dict(),
        resource.to_dict() if resource else None,
        label_index=idx,
        assigned_to_name=_resolve_assignee_name(db, subtask.assigned_to),
    )
    if comment_payload is not None:
        response_data["comment"] = comment_payload
    if standalone_payload:
        response_data["standaloneAttachments"] = standalone_payload
    return BaseController.created(data=response_data)


def _format_resource(r: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    return {
        "_type": "SubtaskResource",
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


def format_subtask_response(
    s: Dict[str, Any],
    resource: Optional[Dict[str, Any]] = None,
    label_index: Optional[LabelIndex] = None,
    base_url: str = "/api/v3",
    *,
    nested_subtasks: Optional[List[Dict[str, Any]]] = None,
    assigned_to_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Format a Subtask response.

    Doc 28: when ``nested_subtasks`` is provided, it's emitted under the
    ``subtasks`` key — recursive structure for tree-rendering FE clients.
    The list endpoint passes the row's pre-built children here; the
    single-GET endpoint omits it (single-row reads stay flat).
    """
    deps = s.get("depends_on") or []
    display_code = (
        label_index.label_of(KIND_SUBTASK, s["id"]) if label_index else None
    )
    deps_display = (
        label_index.labels_of(KIND_SUBTASK, deps) if label_index else []
    )
    out = {
        "_type": "Subtask",
        "_links": {
            "self": {"href": f"{base_url}/subtasks/{s['id']}", "title": s["name"]},
            "task": {"href": f"{base_url}/tasks/{s['task_id']}"},
            "project": {"href": f"{base_url}/projects/{s['project_id']}"},
        },
        "id": s["id"],
        "displayCode": display_code,
        "projectId": s["project_id"],
        "taskId": s["task_id"],
        "parentSubtaskId": s.get("parent_subtask_id"),
        "name": s["name"],
        "description": s["description"],
        "type": s["type"],
        "startDate": s["start_date"],
        "endDate": s["end_date"],
        "actualStartDate": s["actual_start_date"],
        "actualEndDate": s["actual_end_date"],
        "position": s["position"],
        "resourceMode": s.get("resource_mode"),
        "resourceCount": s.get("resource_count"),
        "status": s.get("status"),
        # Doc 41 follow-up: optional single assignee. ``assignedTo`` is
        # the user UUID; ``assignedToName`` is the resolved display name.
        # Both NULL when unassigned.
        "assignedTo": s.get("assigned_to"),
        "assignedToName": assigned_to_name,
        "dependsOn": deps,
        "dependsOnDisplay": deps_display,
        "createdAt": s["created_at"],
        "updatedAt": s["updated_at"],
        "createdBy": s["created_by"],
        "updatedBy": s["updated_by"],
        "deletedAt": s["deleted_at"],
        "resource": _format_resource(resource),
    }
    if nested_subtasks is not None:
        out["subtasks"] = nested_subtasks
    return out


def _resolve_assignee_name(db: Session, user_id: Optional[str]) -> Optional[str]:
    """Single-user name lookup for the response. NULL when unassigned."""
    if not user_id:
        return None
    from ....shared.assignee import bulk_user_name_lookup
    return bulk_user_name_lookup(db, [user_id]).get(user_id)


class SubtaskController:
    @staticmethod
    def create(request: Request, task_id: str, data: SubtaskCreateRequest, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        s, r = create_subtask(
            db,
            task_id=task_id,
            # ``type`` is no longer in the request body; service derives it
            # from the parent task. Cross-type mapping reserved for future.
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
        idx = build_label_index_for_project(db, s.project_id)
        return BaseController.created(data=format_subtask_response(
            s.to_dict(), r.to_dict() if r else None, label_index=idx,
            assigned_to_name=_resolve_assignee_name(db, s.assigned_to),
        ))

    @staticmethod
    def create_nested(
        request: Request,
        parent_subtask_id: str,
        data: SubtaskCreateRequest,
        db: Session,
    ) -> JSONResponse:
        """Doc 24: create a subtask nested under another subtask.

        Same body as the task-scoped create. The service infers the root
        ``task_id`` from the parent subtask and writes
        ``parent_subtask_id`` so the new row sits as the parent's child.
        """
        cuid = getattr(request.state, "user_id", None)
        s, r = create_subtask(
            db,
            parent_subtask_id=parent_subtask_id,
            name=data.name, description=data.description,
            start_date=data.start_date, end_date=data.end_date,
            actual_start_date=data.actual_start_date,
            actual_end_date=data.actual_end_date,
            position=data.position,
            resource_mode=None,
            resource_count=None,
            resource=None, current_user_id=cuid,
            depends_on=data.depends_on,
            status=data.status,
            assigned_to=data.assigned_to,
        )
        idx = build_label_index_for_project(db, s.project_id)
        return BaseController.created(data=format_subtask_response(
            s.to_dict(), r.to_dict() if r else None, label_index=idx,
            assigned_to_name=_resolve_assignee_name(db, s.assigned_to),
        ))

    @staticmethod
    async def create_multipart(
        request: Request, task_id: str, db: Session,
    ) -> JSONResponse:
        """Doc 30: create a task-scoped subtask + optional comment / files."""
        result = await _parse_and_validate_subtask_multipart(request)
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
        cuid = getattr(request.state, "user_id", None)
        s, r = create_subtask(
            db,
            task_id=task_id,
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
        return _persist_subtask_inline(request, db, s, r, body, files)

    @staticmethod
    async def create_nested_multipart(
        request: Request, parent_subtask_id: str, db: Session,
    ) -> JSONResponse:
        """Doc 30 + Doc 24: create a subtask nested under another subtask
        + optional inline comment / files. Same form shape as the
        task-scoped create; the service infers the root ``task_id``
        from the parent subtask."""
        result = await _parse_and_validate_subtask_multipart(request)
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
        cuid = getattr(request.state, "user_id", None)
        # Doc 38: trimmed shape on create.
        s, r = create_subtask(
            db,
            parent_subtask_id=parent_subtask_id,
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
        return _persist_subtask_inline(request, db, s, r, body, files)

    @staticmethod
    def list(request: Request, task_id: str, query: SubtaskListQuery, db: Session) -> JSONResponse:
        """List top-level subtasks under a task with nested children
        embedded recursively (doc 28).

        Response shape:
          - ``total``    — count of top-level subtasks (paginated)
          - ``count``    — top-level rows on this page
          - ``elements`` — top-level rows; each carries a ``subtasks``
                          array with its descendants nested recursively
                          (matches the tree endpoint's subtask node shape).

        Pre-doc-28: the response was a flat list of EVERY subtask under
        the task — top-level + nested — sorted by ``(position, id)``,
        which mixed depths together. The FE rendered each row at the
        same indentation, so nesting was invisible.
        """
        paged = list_subtasks(
            db, task_id=task_id,
            page=query.offset, page_size=query.pageSize,
            include_deleted=query.includeDeleted,
        )
        top_level = list(paged.items)
        nested_flat = list(paged.nested)

        # Label index built once across top-level + nested (single
        # project_id since they're all under the same task).
        idx = (
            build_label_index_for_project(
                db, (top_level[0].project_id if top_level else nested_flat[0].project_id),
            )
            if (top_level or nested_flat) else None
        )

        # Adjacency map: parent_subtask_id → [children domain objects].
        # Sort each bucket by (position, id) so the nested order matches
        # the tree endpoint and the underlying SQL ordering.
        children_by_parent: Dict[str, List] = defaultdict(list)
        for s in nested_flat:
            children_by_parent[s.parent_subtask_id].append(s)
        for bucket in children_by_parent.values():
            bucket.sort(key=lambda x: (x.position, x.id))

        # Doc 41 follow-up: bulk-resolve assignee names across the whole
        # tree (top-level + nested) so each format call gets a name with
        # zero extra queries.
        from ....shared.assignee import bulk_user_name_lookup
        all_uids = (
            [s.assigned_to for s in top_level if s.assigned_to]
            + [s.assigned_to for s in nested_flat if s.assigned_to]
        )
        name_by_uid = bulk_user_name_lookup(db, all_uids)

        def _build(s) -> Dict[str, Any]:
            """Recursive: format ``s`` and embed its children under
            ``subtasks: [...]``. Each leaf row gets ``subtasks: []`` so
            the FE iteration stays uniform (no None / missing key).
            """
            return format_subtask_response(
                s.to_dict(),
                resource=None,
                label_index=idx,
                nested_subtasks=[
                    _build(child) for child in children_by_parent.get(s.id, [])
                ],
                assigned_to_name=name_by_uid.get(s.assigned_to),
            )

        items = [_build(s) for s in top_level]
        payload = {
            "_type": "Collection",
            "_links": {"self": {"href": f"/api/v3/tasks/{task_id}/subtasks?offset={paged.page}&pageSize={paged.page_size}"}},
            "total": paged.total, "count": len(items),
            "pageSize": paged.page_size, "offset": paged.page,
            "_embedded": {"elements": items},
        }
        return BaseController.ok(data=payload)

    @staticmethod
    def get(request: Request, subtask_id: str, db: Session) -> JSONResponse:
        s, r = get_subtask_with_resource(db, subtask_id)
        idx = build_label_index_for_project(db, s.project_id)
        return BaseController.ok(data=format_subtask_response(
            s.to_dict(), r.to_dict() if r else None, label_index=idx,
            assigned_to_name=_resolve_assignee_name(db, s.assigned_to),
        ))

    @staticmethod
    def update(request: Request, subtask_id: str, data: SubtaskUpdateRequest, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        # Doc 38: type / resource_mode / resource_count / resource dropped
        # from the wire. Pass None into the underlying service.
        # Doc 41 follow-up: PATCH ``assignedTo`` distinguishes omitted
        # (no change) from null (unassign). Forward only when present.
        update_kwargs = dict(
            subtask_id=subtask_id,
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
        s, r = update_subtask(db, **update_kwargs)
        idx = build_label_index_for_project(db, s.project_id)
        return BaseController.ok(data=format_subtask_response(
            s.to_dict(), r.to_dict() if r else None, label_index=idx,
            assigned_to_name=_resolve_assignee_name(db, s.assigned_to),
        ))

    @staticmethod
    def delete(request: Request, subtask_id: str, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        delete_subtask(db, subtask_id=subtask_id, current_user_id=cuid)
        return BaseController.no_content()

    @staticmethod
    def restore(request: Request, subtask_id: str, db: Session) -> JSONResponse:
        cuid = getattr(request.state, "user_id", None)
        s = restore_subtask(db, subtask_id=subtask_id, current_user_id=cuid)
        idx = build_label_index_for_project(db, s.project_id)
        return BaseController.ok(data=format_subtask_response(
            s.to_dict(), label_index=idx,
            assigned_to_name=_resolve_assignee_name(db, s.assigned_to),
        ))
