"""FastAPI exception handlers — emit the canonical PMIS envelope.

Failure shape on the wire (monolith parity)::

    Domain / HTTP / Unhandled errors:
    {
      "data": null,
      "message": null,
      "error": {
        "_type": "Error",
        "errorIdentifier": "<lowercase_code>",
        "message": "..."
      },
      "status": <int>
    }

    Pydantic / RequestValidationError errors — RAW FastAPI shape
    (matches monolith ``app/api/v3/projects/schemas.py`` field_validator
    flow which lets RequestValidationError propagate):
    {
      "detail": [
        {"type": "value_error", "loc": [...], "msg": "...", "input": ..., "ctx": ...}
      ]
    }

Duplicated across all 4 services (minus user-svc's TwoFactor handler).
Keep in sync.
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import DomainError
from app.core.response import api_response, format_error
from app.utilities.logger import get_logger


logger = get_logger("pmis.errors")


# Monolith parity (per-module errorIdentifier casing): projects/* return
# lowercase snake_case codes (``validation_error`` / ``not_found``) but
# milestones/activities/tasks/subtasks return TitleCase (``ValidationError``
# / ``NotFoundError``). This is a monolith inconsistency we faithfully
# reproduce so the FE sees the same identifiers on the wire.
_TITLECASE_MODULES = frozenset({
    "milestones", "activities", "tasks", "subtasks",
    # ``tree`` is read-only and lives under /projects/{uuid}/tree, but the
    # monolith uses TitleCase identifiers on its NotFound responses there
    # (distinct from /projects which is lowercase).
    "tree",
    # ``dashboard`` routes return TitleCase ``NotFoundError`` (and
    # ``ValidationError``) on the wire — monolith's ``BaseController``
    # uses the TitleCase identifier even though the path nests under
    # ``/projects/`` for the detail / items endpoints.
    "dashboard",
})
_CODE_TITLECASE_MAP = {
    "validation_error": "ValidationError",
    "not_found": "NotFoundError",
    "conflict": "ConflictError",
    "forbidden": "ForbiddenError",
    "unauthorized": "UnauthorizedError",
}


def _module_style_code(code: str, request_path: str) -> str:
    """Translate generic lowercase codes to TitleCase for milestone /
    activity / task / subtask endpoints — matches monolith convention.

    The path can be either id-scoped (``/.../milestones/{id}``) or
    project-scoped (``/.../projects/{id}/milestones/...``); detection
    is a simple ``in`` check across path segments.

    Comment paths (``/comments`` segment) ALWAYS use lowercase codes
    regardless of which entity collection they are nested under
    (monolith parity — comments module uses ``validation_error`` /
    ``not_found`` even when accessed via /tasks/{id}/comments).

    Attachment paths split THREE ways (monolith inconsistency):
      * ``/projects/{id}/attachments`` — TitleCase ONLY ``not_found``
        (-> ``NotFoundError``); other codes stay lowercase.
      * ``/milestones|activities|tasks|subtasks/{id}/attachments`` —
        ALL lowercase. The attachment paths under M/A/T/S route
        through ``comments._target_helper`` in monolith and inherit
        its lowercase identifiers (``not_found`` / ``validation_error``)
        — distinct from the parent M/A/T/S module which is TitleCase.
      * id-scoped ``/attachments/{id}`` — lowercase (aliased to the
        comment delete route).
    """
    segments = {s for s in request_path.split("/") if s}
    if "comments" in segments:
        return code
    if "attachments" in segments:
        if "projects" in segments:
            # Project-attachment paths TitleCase ONLY ``not_found``.
            if code == "not_found":
                return _CODE_TITLECASE_MAP[code]
            return code
        # M/A/T/S attachment paths (and id-scoped /attachments/{id})
        # are all lowercase — short-circuit BEFORE the M/A/T/S
        # TitleCase rule below.
        return code
    if _TITLECASE_MODULES & segments:
        return _CODE_TITLECASE_MAP.get(code, code)
    return code


def _is_attachment_upload_path(request_path: str) -> bool:
    """``/.../projects/{id}/attachments`` — the PROJECT-scoped attachment
    upload endpoint.

    Monolith parity: only the project-attachment route wraps the
    parser-422 (e.g., empty multipart body) into the canonical envelope
    with message ``"At least one file is required."``. The M/A/T/S
    per-target attachment endpoints intentionally let the raw
    ``{"detail": [...]}`` shape propagate (monolith does the same on
    those routes — the JSON-arm Pydantic error shape is preserved).
    """
    parts = [p for p in request_path.split("/") if p]
    if not parts or parts[-1] != "attachments":
        return False
    return "projects" in set(parts)


# Plural URL segment -> singular kind label for the multipart-parser
# error message wrapper. Mirrors the kinds the monolith uses on the wire
# (lowercase singular: ``milestone`` / ``activity`` / ``task`` /
# ``subtask``).
_MULTIPART_KIND_BY_SEGMENT = {
    "milestones": "milestone",
    "activities": "activity",
    "tasks": "task",
    "subtasks": "subtask",
}


def _multipart_kind_from_path(request_path: str) -> Optional[str]:
    """Return the singular entity kind for a multipart-create URL.

    Walks segments right-to-left so nested /create paths (e.g.
    ``/project/projects/{pid}/milestones/create``) resolve to the
    INNERMOST entity (``milestone``). Returns ``None`` for paths that
    don't target one of the dual-mode entity-create endpoints.

    Monolith parity: attachment paths (``/.../attachments`` and
    ``/.../attachments/{id}``) are EXCLUDED — monolith propagates the
    raw Pydantic ``{"detail": [...]}`` shape on M/A/T/S attachment 422s
    instead of wrapping it as ``"Invalid <kind> form fields."``. Only
    the project-attachment route wraps the empty-body case, and that
    is handled by ``_is_attachment_upload_path`` above this check.
    """
    parts = [p for p in request_path.split("/") if p]
    if "attachments" in parts:
        return None
    for seg in reversed(parts):
        if seg in _MULTIPART_KIND_BY_SEGMENT:
            return _MULTIPART_KIND_BY_SEGMENT[seg]
    return None


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        # Pass exc.details through so publish/lifecycle errors that carry
        # a sub-code (e.g. ``{errorIdentifier: "no_milestones"}``) emit
        # the ``_embedded.details`` block monolith returns.
        code = _module_style_code(exc.code, request.url.path)
        return api_response(
            status=exc.status_code,
            error=format_error(code, exc.message, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return api_response(
            status=exc.status_code,
            error=format_error("http_error", str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Monolith parity:
        # * For JSON-arm Pydantic errors (e.g., schema field validators)
        #   monolith returns the RAW ``{"detail": [...]}`` shape — so do
        #   we. Keeps test_*.sh harnesses that check Pydantic url + ctx
        #   working.
        # * For MULTIPART parser errors raised via the ``Multipart422``
        #   sentinel path on M/A/T/S /create endpoints, monolith returns
        #   the canonical wrapped envelope with
        #   ``errorIdentifier: "validation_error"``, message
        #   ``"Invalid <kind> form fields."``, and the per-field error
        #   list under ``_embedded.details.errors``. We mirror that
        #   shape when the content-type is multipart and the path
        #   targets a known entity collection.
        errors = jsonable_encoder(
            exc.errors(),
            custom_encoder={ValueError: lambda v: str(v)},
        )
        content_type = (request.headers.get("content-type") or "").lower()
        if content_type.startswith("multipart/form-data"):
            # Attachment-upload paths (``/.../attachments``) carry only
            # one required field (``files``). Monolith collapses the
            # per-field error list into a short ``"At least one file is
            # required."`` message with no ``_embedded.details``.
            if _is_attachment_upload_path(request.url.path):
                return api_response(
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    error=format_error(
                        "validation_error",
                        "At least one file is required.",
                    ),
                )
            kind = _multipart_kind_from_path(request.url.path)
            if kind is not None:
                return api_response(
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    error=format_error(
                        "validation_error",
                        f"Invalid {kind} form fields.",
                        details={"errors": errors},
                    ),
                )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": errors},
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        # A DB constraint violation (e.g. the per-parent uq_*_position_live
        # uniqueness index when two creates race on the same parent) must
        # surface as a clean 409, not a 500. The request's DB session is
        # rolled back by the get_db dependency teardown on close.
        logger.warning("IntegrityError -> 409 (%s): %s", request.url.path, exc)
        code = _module_style_code("conflict", request.url.path)
        return api_response(
            status=status.HTTP_409_CONFLICT,
            error=format_error(
                code, "The request conflicts with the current state of the resource.",
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return api_response(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error=format_error("internal_server_error", "Internal server error"),
        )
