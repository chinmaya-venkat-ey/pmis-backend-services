"""Milestones controller."""
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
from ....infrastructure.db.repositories.project_repository import ProjectRepository
from ....shared.labels import (
    KIND_MILESTONE,
    LabelIndex,
    build_label_index_for_project,
)
from ....core.errors import NotFoundError

# Doc 30: inline attachments at create time. The multipart path reuses
# the standalone comment + attachment services (via the shared dispatcher)
# so the persistence semantics are identical to the post-create endpoints.
from .._inline_attachments import (
    Multipart422,
    extract_files_from_form,
    parse_form_fields,
    persist_inline_comment_or_files,
    pre_validate_files,
    sanitize_pydantic_errors,
)

from .schemas import MilestoneCreateRequest, MilestoneUpdateRequest, MilestoneListQuery
from .services import (
    create_milestone, get_milestone, list_milestones,
    update_milestone, delete_milestone, restore_milestone,
)


# Form-field spec for the multipart create path. Mirrors the keys
# accepted by MilestoneCreateRequest (using its alias names).
_REQUIRED_STRING_KEYS = ("name",)
_OPTIONAL_STRING_KEYS = ("description", "startDate", "endDate", "status")
_INT_KEYS = ("position",)
_ARRAY_KEYS = ("dependsOn", "vendors")


def _verify_project_exists(db: Session, project_uuid: str) -> None:
    """Raises NotFoundError if no live project with this id (id is the UUID)."""
    if not ProjectRepository(db).exists_by_id(project_uuid):
        raise NotFoundError("The project could not be found.")


def format_milestone_response(
    m: dict,
    label_index: Optional[LabelIndex] = None,
    base_url: str = "/api/v3",
) -> Dict[str, Any]:
    """HAL+JSON shape for one milestone.

    When ``label_index`` is provided, the response includes ``displayCode``
    (this milestone's label, e.g. "M1") and ``dependsOnDisplay`` (labels
    for each id in ``dependsOn``). Pass ``None`` only on paths where the
    label index isn't worth building (none in practice — every controller
    here builds one).
    """
    deps = m.get("depends_on", []) or []
    display_code = (
        label_index.label_of(KIND_MILESTONE, m["id"]) if label_index else None
    )
    deps_display = (
        label_index.labels_of(KIND_MILESTONE, deps) if label_index else []
    )
    return {
        "_type": "Milestone",
        "_links": {
            "self": {"href": f"{base_url}/milestones/{m['id']}", "title": m["name"]},
            "project": {"href": f"{base_url}/projects/{m['project_id']}"},
        },
        "id": m["id"],
        "displayCode": display_code,
        "projectId": m["project_id"],
        "name": m["name"],
        "description": m["description"],
        "startDate": m["start_date"],
        "endDate": m["end_date"],
        "position": m["position"],
        "status": m.get("status", "not_completed"),
        "dependsOn": deps,
        "dependsOnDisplay": deps_display,
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
            position=None,  # doc 38: position is PATCH-only
            current_user_id=current_user_id,
            status=None,  # doc 38: status is PATCH-only
            depends_on=None,  # doc 38: dependsOn is PATCH-only
            vendor_ids=None,  # doc 38: vendors are PATCH-only
        )
        idx = build_label_index_for_project(db, project_id)
        return BaseController.created(data=format_milestone_response(m.to_dict(), idx))

    @staticmethod
    async def create_multipart(
        request: Request, project_uuid: str, db: Session,
    ) -> JSONResponse:
        """Doc 30: create a milestone PLUS optional inline comment / files.

        Multipart form shape:
          name, description, startDate, endDate, position,
          status, dependsOn, vendors      — milestone fields (same as JSON,
                                            arrays JSON-encoded)
          body                            — optional comment text
          files                           — optional file uploads (repeatable)

        Behavior:
          * If neither ``body`` nor ``files`` present: equivalent to the
            JSON path (just creates the milestone).
          * If ``body`` present (with or without files): a comment row is
            created against the milestone, and any files are bound to
            that comment.
          * If ``files`` present without ``body``: each file becomes a
            standalone attachment on the milestone (no comment row).

        Failure handling:
          * Pre-validation (milestone fields, file extensions, file
            sizes) catches the common bad inputs before any DB write
            and returns 422 — no milestone is created in those cases.
          * If the file-persistence step fails AFTER the milestone is
            created (rare — e.g. transient storage I/O error), the
            milestone is left in place. The error response surfaces
            the milestone id so the FE can retry the upload via the
            standalone comment / attachment endpoints rather than
            re-creating the milestone.
        """
        form = await request.form()

        # ---- 1. Parse + validate milestone fields ------------------------
        try:
            milestone_fields = parse_form_fields(
                form,
                required_string_keys=_REQUIRED_STRING_KEYS,
                string_keys=_OPTIONAL_STRING_KEYS,
                int_keys=_INT_KEYS,
                array_keys=_ARRAY_KEYS,
            )
        except Multipart422 as e:
            return BaseController.error(
                format_error_response(
                    error_type="validation_error",
                    message="Invalid milestone form fields.",
                    details={"errors": e.detail},
                ),
                status=422,
            )

        try:
            data = MilestoneCreateRequest.model_validate(milestone_fields)
        except ValidationError as e:
            return BaseController.error(
                format_error_response(
                    error_type="validation_error",
                    message="Milestone field validation failed.",
                    details={"errors": sanitize_pydantic_errors(e.errors())},
                ),
                status=422,
            )

        body = form.get("body") or ""
        files = extract_files_from_form(form)

        # ---- 1b. Pre-validate files BEFORE creating the milestone --------
        # Catches the common "bad file" cases (oversize, disallowed ext)
        # so the milestone isn't half-created when a file is rejected.
        # Storage I/O failures during the actual write are still possible
        # but rare — those return a 500-ish response with the
        # already-created milestone id surfaced in the details.
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

        # ---- 2. Create milestone (existing service, commits) -------------
        _verify_project_exists(db, project_uuid)
        project_id = project_uuid
        current_user_id = getattr(request.state, "user_id", None)

        m = create_milestone(
            db,
            project_id=project_id,
            name=data.name,
            description=data.description,
            start_date=data.start_date,
            end_date=data.end_date,
            position=None,  # doc 38: position is PATCH-only
            current_user_id=current_user_id,
            status=None,  # doc 38: status is PATCH-only
            depends_on=None,  # doc 38: dependsOn is PATCH-only
            vendor_ids=None,  # doc 38: vendors are PATCH-only
        )

        # ---- 3. Inline comment / attachments (optional) ------------------
        comment_payload, standalone_payload, err_tuple = persist_inline_comment_or_files(
            db,
            target_kind="milestone",
            target_id=m.id,
            body=body if isinstance(body, str) else "",
            files=files,
            current_user_id=current_user_id,
            format_comment_response=format_comment_response,
            format_attachment_response=format_attachment_response,
            parent_label="Milestone",
            retry_endpoint_path=f"POST /api/v3/milestones/{m.id}/comments",
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

        # ---- 4. Build response -------------------------------------------
        idx = build_label_index_for_project(db, project_id)
        response_data = format_milestone_response(m.to_dict(), idx)
        if comment_payload is not None:
            response_data["comment"] = comment_payload
        if standalone_payload:
            response_data["standaloneAttachments"] = standalone_payload
        return BaseController.created(data=response_data)

    @staticmethod
    def list(request: Request, project_uuid: str, query: MilestoneListQuery, db: Session) -> JSONResponse:
        _verify_project_exists(db, project_uuid)
        project_id = project_uuid  # project_id IS the UUID
        paged = list_milestones(
            db, project_id=project_id,
            page=query.offset, page_size=query.pageSize,
            include_deleted=query.includeDeleted,
        )
        idx = build_label_index_for_project(db, project_id)
        items = [format_milestone_response(m.to_dict(), idx) for m in paged.items]
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
        idx = build_label_index_for_project(db, m.project_id)
        return BaseController.ok(data=format_milestone_response(m.to_dict(), idx))

    @staticmethod
    def update(request: Request, milestone_id: str, data: MilestoneUpdateRequest, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        # Doc 38: status / dependsOn / vendors / position were removed
        # from the CREATE schema but PATCH still accepts them — that's the
        # whole point of the trim. Pass the schema fields through here.
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
            depends_on=data.depends_on,
            vendor_ids=None,  # doc 39: vendors removed from milestone wire surface
        )
        idx = build_label_index_for_project(db, m.project_id)
        return BaseController.ok(data=format_milestone_response(m.to_dict(), idx))

    @staticmethod
    def delete(request: Request, milestone_id: str, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        delete_milestone(db, milestone_id=milestone_id, current_user_id=current_user_id)
        return BaseController.no_content()

    @staticmethod
    def restore(request: Request, milestone_id: str, db: Session) -> JSONResponse:
        current_user_id = getattr(request.state, "user_id", None)
        m = restore_milestone(db, milestone_id=milestone_id, current_user_id=current_user_id)
        idx = build_label_index_for_project(db, m.project_id)
        return BaseController.ok(data=format_milestone_response(m.to_dict(), idx))
