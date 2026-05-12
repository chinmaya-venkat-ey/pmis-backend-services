"""
Project controller - orchestrates requests and responses.

URL path parameter is always ``project_uuid`` (the public handle). The
controller resolves UUID -> internal integer id via the repository, then
passes the int to the service layer (which remains id-based for fast FK joins
and for symmetry with the services/helpers exposed to other modules).
"""
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from pydantic import ValidationError

from ....core.base_controller import BaseController
from ....core.dependencies import get_current_user_id
from ....core.errors import NotFoundError
from ....core.response import (
    format_attachment_response,
    format_collection_response,
    format_comment_response,
    format_error_response,
    format_project_response,
)
from ....infrastructure.db.repositories.project_repository import ProjectRepository

# Doc-30 inline-attachments pattern (mirrors M/A/T/S) — multipart variant
# of POST /projects/create accepts ``files[]`` plus the same project fields
# as the JSON variant. Files land in the comments table with body=NULL,
# polymorphic on ``target_kind="project"``.
from .._inline_attachments import (
    Multipart422,
    extract_files_from_form,
    parse_form_fields,
    persist_inline_comment_or_files,
    pre_validate_files,
    sanitize_pydantic_errors,
)

from .schemas import (
    ProjectCloseRequest,
    ProjectCreateRequest,
    ProjectListQuery,
    ProjectUpdateRequest,
    ProjectUpsertRequest,
)
from .services import (
    close_project,
    create_project,
    delete_project,
    get_project_by_id,
    list_projects,
    publish_project,
    save_project_setup,
    update_project,
    upsert_project,
)


_HTTP_BY_ERROR_TYPE = {
    "validation_error": 422,
    "invalid_field": 422,
    "invalid_publish": 422,  # doc 27: empty / no-milestone publish gate
    "invalid_transition": 409,
    "invalid_source": 409,
    "already_exists": 409,
    "project_locked": 409,
    "forbidden": 403,
    "not_found": 404,
    "internal_error": 500,
}


def _error_response(result, *, default_status: int = 400) -> JSONResponse:
    payload: Dict[str, Any] = {
        "_type": "Error",
        "errorIdentifier": result.error_type,
        "message": result.error,
    }
    if result.details:
        payload["_embedded"] = {"details": result.details}
    status = _HTTP_BY_ERROR_TYPE.get(result.error_type, default_status)
    return BaseController.error(payload, status=status)


def _actor_is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


def _project_exists(db: Session, project_uuid: str) -> bool:
    """True if a live project with this id (id IS the UUID) exists."""
    return ProjectRepository(db).exists_by_id(project_uuid)


class ProjectController:
    """Controller for project operations."""

    @staticmethod
    def create(request: Request, data: ProjectCreateRequest, db: Session) -> JSONResponse:
        actor_id = get_current_user_id(request)
        # Doc 38: ``public`` / ``category`` / ``categoryOther`` /
        # ``categoryOtherReason`` were removed from the request schema.
        # Pass None so the service stores defaults (DB columns kept for
        # legacy rows but new rows leave them empty).
        result = create_project(
            db=db,
            actor_id=actor_id,
            name=data.name,
            description=data.description,
            active=data.active,
            public=False,
            status_explanation=data.statusExplanation,
            parent_id=data.parentId,
            status=data.status,
            owner=data.owner,
            owner_other=data.ownerOther,
            category=None,
            category_other=None,
            category_other_reason=None,
            vendor_ids=data.vendorIds,
            start_date=data.start_date,
            end_date=data.end_date,
        )
        if not result.is_success():
            return _error_response(result)
        formatted = format_project_response(result.data.to_dict(), "/api/v3")
        return BaseController.created(data=formatted)

    # Form-field spec for the multipart create path. Mirrors the keys
    # accepted by ProjectCreateRequest (using its alias names). Files
    # are extracted separately via ``extract_files_from_form``.
    _MULTIPART_REQUIRED_STRING_KEYS = ("name",)
    _MULTIPART_OPTIONAL_STRING_KEYS = (
        "description", "statusExplanation", "parentId",
        "status", "owner", "ownerOther",
        "startDate", "endDate",
    )
    _MULTIPART_INT_KEYS = ()
    _MULTIPART_ARRAY_KEYS = ("vendorIds",)

    @staticmethod
    async def create_multipart(
        request: Request, db: Session,
    ) -> JSONResponse:
        """Multipart variant of POST /projects/create.

        Accepts the same project fields as the JSON path PLUS optional
        ``files[]`` for documents to attach (project charter, scope
        doc, RFP, etc.). Files land in the comments table with
        ``body=NULL`` and ``target_kind="project"`` — the FE never sees
        a /comments URL for projects; the surface stays
        ``/projects/{id}/attachments``.

        Failure handling matches the M/A/T/S multipart create:
        pre-validation (project fields, file extensions, file sizes,
        magic-byte content sniff) catches the common bad inputs before
        any DB write. If file persistence fails after the project row
        is created, the project is left in place and the response
        surfaces the project id so the FE can retry the upload via
        POST /projects/{id}/attachments.
        """
        form = await request.form()

        # ---- 1. Parse + validate project fields --------------------------
        try:
            project_fields = parse_form_fields(
                form,
                required_string_keys=ProjectController._MULTIPART_REQUIRED_STRING_KEYS,
                string_keys=ProjectController._MULTIPART_OPTIONAL_STRING_KEYS,
                int_keys=ProjectController._MULTIPART_INT_KEYS,
                array_keys=ProjectController._MULTIPART_ARRAY_KEYS,
            )
        except Multipart422 as e:
            return BaseController.error(
                format_error_response(
                    error_type="validation_error",
                    message="Invalid project form fields.",
                    details={"errors": e.detail},
                ),
                status=422,
            )

        try:
            data = ProjectCreateRequest.model_validate(project_fields)
        except ValidationError as e:
            return BaseController.error(
                format_error_response(
                    error_type="validation_error",
                    message="Project field validation failed.",
                    details={"errors": sanitize_pydantic_errors(e.errors())},
                ),
                status=422,
            )

        files = extract_files_from_form(form)

        # ---- 1b. Pre-validate files BEFORE creating the project ----------
        # Size + extension + magic-byte content sniff. A bad file here
        # means no project row is created.
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

        # ---- 2. Create project (existing service, commits) ---------------
        actor_id = get_current_user_id(request)
        result = create_project(
            db=db,
            actor_id=actor_id,
            name=data.name,
            description=data.description,
            active=data.active,
            public=False,
            status_explanation=data.statusExplanation,
            parent_id=data.parentId,
            status=data.status,
            owner=data.owner,
            owner_other=data.ownerOther,
            category=None,
            category_other=None,
            category_other_reason=None,
            vendor_ids=data.vendorIds,
            start_date=data.start_date,
            end_date=data.end_date,
        )
        if not result.is_success():
            return _error_response(result)
        project = result.data

        # ---- 3. Persist inline attachments (files-only, body=None) -------
        # Project surface intentionally does NOT expose a body field —
        # the FE only ever uploads files here, not comment text. The
        # helper still requires a string-or-None for body, so pass "".
        _comment_payload, _standalone, err_tuple = persist_inline_comment_or_files(
            db,
            target_kind="project",
            target_id=project.id,
            body="",  # always empty for project attachments
            files=files,
            current_user_id=actor_id,
            format_comment_response=format_comment_response,
            format_attachment_response=format_attachment_response,
            parent_label="Project",
            retry_endpoint_path=f"POST /api/v3/projects/{project.id}/attachments",
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

        # ---- 4. Build response (eagerly includes attachments) ------------
        formatted = format_project_response(project.to_dict(), "/api/v3", db=db)
        return BaseController.created(data=formatted)

    @staticmethod
    def list(request: Request, query: ProjectListQuery, db: Session) -> JSONResponse:
        # Doc 44 round 8 (mirrored from monolith) — non-admin tiers see
        # only post-publish projects. Anonymous callers (no user_id) are
        # treated as admin so existing test/dev paths that hit the list
        # without a token still see every row.
        caller_id = get_current_user_id(request)
        caller_is_admin = True
        if caller_id is not None:
            from ....infrastructure.db.repositories.rbac_repository import (
                RbacRepository,
            )
            caller_is_admin = RbacRepository(db).user_has_admin_role(caller_id)
        result = list_projects(
            db=db,
            page=query.offset,
            page_size=query.pageSize,
            active=query.active,
            public=None,  # doc 38: dropped from list-query schema
            include_deleted=query.includeDeleted,
            caller_is_admin=caller_is_admin,
        )
        if not result.is_success():
            return _error_response(result, default_status=500)
        paginated = result.data
        project_dicts = [p.to_dict() for p in paginated.items]
        formatted = format_collection_response(
            items=project_dicts,
            total=paginated.total,
            page=paginated.page,
            page_size=paginated.page_size,
            base_url="/api/v3",
            collection_type="projects",
        )
        return BaseController.ok(data=formatted)

    @staticmethod
    def get(request: Request, project_uuid: str, db: Session) -> JSONResponse:
        result = get_project_by_id(db, project_uuid)
        if not result.is_success():
            return _error_response(result, default_status=404)

        # Doc 44 round 8 (mirrored from monolith) — non-admin tiers cannot
        # view pre-publish projects (status in {draft, new}). 404 keeps
        # the response shape consistent with the list-side silent hide.
        caller_id = get_current_user_id(request)
        project_status = getattr(result.data, "status", None)
        if (
            caller_id is not None
            and project_status in ("draft", "new")
        ):
            from ....infrastructure.db.repositories.rbac_repository import (
                RbacRepository,
            )
            if not RbacRepository(db).user_has_admin_role(caller_id):
                return _error_response(_NotFoundResult(), default_status=404)

        formatted = format_project_response(result.data.to_dict(), "/api/v3", db=db)
        return BaseController.ok(data=formatted)

    @staticmethod
    def update(
        request: Request,
        project_uuid: str,
        data: ProjectUpdateRequest,
        db: Session,
    ) -> JSONResponse:
        if not _project_exists(db, project_uuid):
            return _error_response(_NotFoundResult(), default_status=404)
        pid = project_uuid  # project.id IS the UUID
        actor_id = get_current_user_id(request)
        # Doc 38: public / category* removed from update schema.
        patch: Dict[str, Any] = {
            "name": data.name,
            "description": data.description,
            "active": data.active,
            "status_explanation": data.statusExplanation,
            "parent_id": data.parentId,
            "status": data.status,
            "owner": data.owner,
            "owner_other": data.ownerOther,
            "start_date": data.start_date,
            "end_date": data.end_date,
            "actual_start_date": data.actual_start_date,
            "actual_end_date": data.actual_end_date,
        }
        # vendor_ids is an Optional[List[str]]. None means "don't touch the
        # vendor list"; an empty list means "clear"; a non-empty list means
        # "replace". The service handles it outside the column-whitelist path
        # because vendors live in an association table.
        result = update_project(
            db, pid,
            actor_id=actor_id,
            patch=patch,
            vendor_ids=data.vendorIds,
        )
        if not result.is_success():
            return _error_response(result)
        formatted = format_project_response(result.data.to_dict(), "/api/v3")
        return BaseController.ok(data=formatted)

    @staticmethod
    def delete(request: Request, project_uuid: str, db: Session) -> JSONResponse:
        if not _project_exists(db, project_uuid):
            return _error_response(_NotFoundResult(), default_status=404)
        pid = project_uuid  # project.id IS the UUID
        actor_id = get_current_user_id(request)
        result = delete_project(db, pid, actor_id=actor_id)
        if not result.is_success():
            return _error_response(result, default_status=404)
        return BaseController.no_content()

    @staticmethod
    def publish(request: Request, project_uuid: str, db: Session) -> JSONResponse:
        if not _project_exists(db, project_uuid):
            return _error_response(_NotFoundResult(), default_status=404)
        pid = project_uuid  # project.id IS the UUID
        actor_id = get_current_user_id(request)
        result = publish_project(
            db, pid,
            actor_id=actor_id,
            actor_is_admin=_actor_is_admin(request),
        )
        if not result.is_success():
            return _error_response(result)
        formatted = format_project_response(result.data.to_dict(), "/api/v3")
        return BaseController.ok(data=formatted)

    @staticmethod
    def close(
        request: Request,
        project_uuid: str,
        data: ProjectCloseRequest,
        db: Session,
    ) -> JSONResponse:
        if not _project_exists(db, project_uuid):
            return _error_response(_NotFoundResult(), default_status=404)
        pid = project_uuid  # project.id IS the UUID
        actor_id = get_current_user_id(request)
        result = close_project(
            db, pid,
            actor_id=actor_id,
            actor_is_admin=_actor_is_admin(request),
            reason=data.reason if data is not None else None,
        )
        if not result.is_success():
            return _error_response(result)
        formatted = format_project_response(result.data.to_dict(), "/api/v3")
        return BaseController.ok(data=formatted)

    @staticmethod
    def save(request: Request, project_uuid: str, db: Session) -> JSONResponse:
        """Handle the 'Save Project' action: new -> draft if a milestone exists.

        The service itself raises not_found when the project is missing, so we
        don't need the ``_project_exists`` pre-check the other handlers use.
        """
        actor_id = get_current_user_id(request)
        result = save_project_setup(db, project_uuid, actor_id=actor_id)
        if not result.is_success():
            return _error_response(result)
        formatted = format_project_response(result.data.to_dict(), "/api/v3")
        return BaseController.ok(data=formatted)

    @staticmethod
    def upsert(
        request: Request,
        project_uuid: str,
        data: ProjectUpsertRequest,
        db: Session,
    ) -> JSONResponse:
        """
        Idempotent create-or-update of a project by UUID (wizard flow).

        Returns 201 on fresh insert, 200 on update, 403 on ownership violation,
        404 if parent_id references a missing project.
        """
        current_user_login = getattr(request.state, "user_login", None)
        is_admin = _actor_is_admin(request)

        # Doc 38: public / category* removed from upsert schema.
        result = upsert_project(
            db=db,
            id=project_uuid,
            name=data.name,
            current_user_login=current_user_login,
            is_admin=is_admin,
            description=data.description,
            active=data.active,
            public=False,
            status_explanation=data.statusExplanation,
            parent_id=data.parentId,
            status=data.status,
            owner=data.owner,
            owner_other=data.ownerOther,
            category=None,
            category_other=None,
            category_other_reason=None,
            start_date=data.start_date,
            end_date=data.end_date,
        )
        if not result.is_success():
            return _error_response(result)

        project, created = result.data
        formatted = format_project_response(project.to_dict(), "/api/v3")
        # Surface insert-vs-update for the wizard frontend.
        formatted["_created"] = created
        if created:
            return BaseController.created(data=formatted)
        return BaseController.ok(data=formatted)


class _NotFoundResult:
    """Tiny adapter so _error_response can emit a NotFound without a ServiceResult."""
    error_type = "not_found"
    error = "The project could not be found."
    details = None

    def is_success(self):
        return False
