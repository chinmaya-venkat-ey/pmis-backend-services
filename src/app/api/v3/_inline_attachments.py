"""Doc 30: shared multipart helpers for create endpoints.

Milestone, activity, task, and subtask create endpoints all support a
dual-mode body (``application/json`` OR ``multipart/form-data``). The
multipart path's plumbing — file pre-validation, form-field parsing,
Pydantic-error sanitization, error-type → HTTP-status mapping, and the
"persist a comment / standalone attachments" routing — is identical
across all four entities. Centralising here keeps the four controllers
focused on their own create logic.

Public surface (intentionally narrow — only what controllers need):

  * ``Multipart422``                — sentinel exception for parser errors
  * ``parse_form_fields``           — generic form → dict for Pydantic
  * ``extract_files_from_form``     — pull ``files`` uploads out
  * ``pre_validate_files``          — size + extension check pre-DB
  * ``sanitize_pydantic_errors``    — strip non-JSON-serialisable ctx
  * ``status_for_error``            — service error_type → HTTP status
  * ``persist_inline_comment_or_files`` — route body/files to the right
                                      existing service after the parent
                                      row is created

Each entity supplies its own field spec (which fields are strings, ints,
JSON-encoded arrays, or JSON-encoded nested objects); the helpers stay
entity-agnostic.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from fastapi import Request, UploadFile
from pydantic import BaseModel, ValidationError

from ...core.config import settings
from ...infrastructure.storage.file_storage import file_extension
from .attachments.services import upload_standalone_attachment
from .comments.services import create_comment


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sentinel for parser-level rejections (malformed int, malformed JSON array,
# malformed JSON object). Carries a Pydantic-style ``detail`` list so the
# caller's error response shape matches the schema-validator path.
# ---------------------------------------------------------------------------
class Multipart422(Exception):
    def __init__(self, detail: List[Dict[str, Any]]):
        super().__init__("multipart validation failed")
        self.detail = detail


# ---------------------------------------------------------------------------
# Form-field parser. Every entity's form has the same four shapes:
#   - plain strings (``name``, ``status``)
#   - integers      (``position``, ``resourceCount``)
#   - JSON arrays   (``dependsOn``, ``vendors``)
#   - JSON objects  (``resource``  — only on activity/details, but the
#                    machinery is generic)
# Pass the keys for each shape; the parser drops everything else and
# returns a dict ready for ``Model.model_validate(...)``.
# ---------------------------------------------------------------------------
def parse_form_fields(
    form,
    *,
    string_keys: Iterable[str] = (),
    required_string_keys: Iterable[str] = (),
    int_keys: Iterable[str] = (),
    array_keys: Iterable[str] = (),
    object_keys: Iterable[str] = (),
) -> Dict[str, Any]:
    """Convert a multipart form into a dict for Pydantic validation.

    * ``string_keys``           — pass through as strings. Empty strings
                                  are skipped (Swagger UI auto-fills
                                  blanks; clients shouldn't be punished).
    * ``required_string_keys``  — passed through verbatim (empty strings
                                  stay so Pydantic's ``min_length`` can
                                  fire). Used for ``name`` etc.
    * ``int_keys``              — coerced via ``int(...)``. Empty / None
                                  skipped.
    * ``array_keys``            — JSON-decoded; must decode to a list.
    * ``object_keys``           — JSON-decoded; must decode to a dict.

    Raises ``Multipart422`` for parse-level failures (non-int, non-JSON,
    wrong JSON shape). Pydantic handles the rest after this returns.
    """
    fields: Dict[str, Any] = {}
    bad: List[Dict[str, Any]] = []

    for key in required_string_keys:
        if key in form:
            v = form[key]
            if isinstance(v, str):
                # Required: pass empty strings through so Pydantic's
                # min_length=1 produces the right error message.
                fields[key] = v

    for key in string_keys:
        if key in form:
            v = form[key]
            if isinstance(v, str):
                if v == "":
                    # Swagger UI auto-fills cleared inputs with "" — treat
                    # these as omitted for optional fields. (Required
                    # string fields are handled above.)
                    continue
                fields[key] = v

    for key in int_keys:
        if key in form and form[key] not in ("", None):
            raw = form[key]
            try:
                fields[key] = int(raw)
            except (TypeError, ValueError):
                bad.append({
                    "loc": ["body", key],
                    "msg": f"{key} must be an integer",
                    "type": "value_error",
                })

    for key in array_keys:
        if key in form and form[key] not in ("", None):
            raw = form[key]
            if not isinstance(raw, str):
                bad.append({
                    "loc": ["body", key],
                    "msg": f"{key} must be a JSON-encoded array string",
                    "type": "type_error",
                })
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                bad.append({
                    "loc": ["body", key],
                    "msg": f"{key} must be a JSON-encoded array string (got {raw!r})",
                    "type": "value_error",
                })
                continue
            if not isinstance(parsed, list):
                bad.append({
                    "loc": ["body", key],
                    "msg": f"{key} must decode to a JSON array",
                    "type": "type_error",
                })
                continue
            fields[key] = parsed

    for key in object_keys:
        if key in form and form[key] not in ("", None):
            raw = form[key]
            if not isinstance(raw, str):
                bad.append({
                    "loc": ["body", key],
                    "msg": f"{key} must be a JSON-encoded object string",
                    "type": "type_error",
                })
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                bad.append({
                    "loc": ["body", key],
                    "msg": f"{key} must be a JSON-encoded object string (got {raw!r})",
                    "type": "value_error",
                })
                continue
            if not isinstance(parsed, dict):
                bad.append({
                    "loc": ["body", key],
                    "msg": f"{key} must decode to a JSON object",
                    "type": "type_error",
                })
                continue
            fields[key] = parsed

    if bad:
        raise Multipart422(bad)
    return fields


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
def extract_files_from_form(form) -> List[UploadFile]:
    """Return every ``files`` entry that has a real filename.

    Some clients submit a phantom ``files`` field with empty filename
    when the user picked nothing — drop those so the empty-multipart
    case stays clean.
    """
    raw = form.getlist("files") if "files" in form else []
    out: List[UploadFile] = []
    for item in raw:
        if hasattr(item, "filename") and item.filename:
            out.append(item)
    return out


def _allowed_extensions() -> set[str]:
    raw = settings.ATTACHMENTS_ALLOWED_EXTENSIONS or ""
    return {e.strip().lower().lstrip(".") for e in raw.split(",") if e.strip()}


def pre_validate_files(files: List[UploadFile]) -> Optional[Dict[str, Any]]:
    """Reject obvious "bad file" cases BEFORE the parent row is inserted.

    This is the central guarantee of the doc-30 multipart path: a
    rejected file means no parent row was created, so the FE never has
    to clean up a half-created milestone / activity / task / subtask.

    Mirrors the per-file checks that ``create_comment`` and
    ``upload_standalone_attachment`` do internally (so we catch them
    early). Returns ``None`` on success or an error-shape dict that the
    caller wraps in the standard error envelope.
    """
    if not files:
        return None
    allowed = _allowed_extensions()
    max_bytes = settings.ATTACHMENTS_MAX_BYTES
    for upload in files:
        upload.file.seek(0, 2)
        size = upload.file.tell()
        upload.file.seek(0)
        if size > max_bytes:
            return {
                "error_type": "validation_error",
                "message": (
                    f"File '{upload.filename}' is {size} bytes; "
                    f"maximum is {max_bytes}."
                ),
                "details": {
                    "file": upload.filename, "size": size, "max": max_bytes,
                },
            }
        ext = file_extension(upload.filename or "")
        if not ext or ext not in allowed:
            return {
                "error_type": "validation_error",
                "message": (
                    f"File '{upload.filename}' has disallowed extension "
                    f"'.{ext}'. Allowed: {', '.join(sorted(allowed))}."
                ),
                "details": {"file": upload.filename, "extension": ext},
            }
    return None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
def sanitize_pydantic_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip non-JSON-serialisable values from Pydantic v2 errors.

    Pydantic v2's ``ValidationError.errors()`` populates ``ctx`` with the
    raw underlying exception (e.g. a ``ValueError`` instance) for
    field validators. ``json.dumps`` chokes on those, which previously
    surfaced a legitimate 422 as a 500 in our envelope renderer.

    We strip ``ctx`` outright (the FE only needs ``loc`` / ``msg`` /
    ``type`` for display) and stringify any other unexpected exception
    values defensively.
    """
    cleaned: List[Dict[str, Any]] = []
    for err in errors or []:
        out: Dict[str, Any] = {}
        for k, v in err.items():
            if k == "ctx":
                continue
            if k == "url":
                continue
            if isinstance(v, Exception):
                out[k] = str(v)
            else:
                out[k] = v
        cleaned.append(out)
    return cleaned


def status_for_error(error_type: Optional[str]) -> int:
    """Map service-result error_type strings to HTTP status codes."""
    return {
        "validation_error": 422,
        "authentication_error": 401,
        "authorization_error": 403,
        "not_found": 404,
        "storage_unavailable": 503,
        "internal_error": 500,
    }.get(error_type or "", 500)


# ---------------------------------------------------------------------------
# Inline comment / attachment persistence — the post-create dispatcher
# ---------------------------------------------------------------------------
def persist_inline_comment_or_files(
    db,
    *,
    target_kind: str,
    target_id: str,
    body: str,
    files: List[UploadFile],
    current_user_id: Optional[int],
    format_comment_response,
    format_attachment_response,
    parent_label: str,
    retry_endpoint_path: str,
) -> Tuple[
    Optional[Dict[str, Any]],   # comment_payload (or None when nothing was sent)
    List[Dict[str, Any]],        # standalone_payload (always [] post-doc-34)
    Optional[Dict[str, Any]],    # error tuple (error_response_dict, status) or None
]:
    """Route the inline comment/files for a freshly-created parent row.

    Doc 35 simplification: a single ``create_comment`` call now handles
    every shape (body-only, files-only, body+files) by writing one row
    to the unified comments table. The historical "files only goes to
    a separate standalone-attachment endpoint" branch is gone — files
    without a body just produce a row with NULL body and a populated
    JSON ``attachments`` list.

    Returns a 3-tuple:
      * ``(comment_payload, [], None)``       — body and/or files were sent
      * ``(None, [], None)``                  — neither (nothing to do)
      * ``(None, [], (error_dict, status))``  — failure mid-way; caller
                                                renders the error envelope.

    ``standalone_payload`` is kept in the return tuple shape for source
    compatibility with the four entity controllers; it always returns
    ``[]`` post-doc-34 since standalone attachments are now just
    body-NULL comment rows. Controllers can drop their
    ``standaloneAttachments`` response key — included in the comment
    payload's ``attachments`` JSON list when present — but leaving the
    branch in place is harmless.
    """
    body_clean = (body or "").strip()
    files = files or []

    if not body_clean and not files:
        return None, [], None

    result = create_comment(
        db,
        target_kind=target_kind,
        target_id=target_id,
        body=body_clean or None,
        files=files,
        author_user_id=current_user_id,
    )
    if result.is_success():
        return format_comment_response(result.data.to_dict()), [], None

    _log.warning(
        "Doc 30 inline comment failed for %s %s: %s",
        target_kind, target_id, result.error,
    )
    return None, [], (
        {
            "error_type": result.error_type or "internal_error",
            "message": (
                f"{parent_label} {target_id} was created, but the inline "
                f"comment / attachment failed: {result.error}. You can "
                f"retry the upload via {retry_endpoint_path}."
            ),
            "details": {
                "id": target_id,
                "originalError": result.details,
            },
        },
        status_for_error(result.error_type),
    )


# ---------------------------------------------------------------------------
# Route-layer dispatch helper.
#
# Each create route is signature-typed as ``Request`` (so FastAPI doesn't
# auto-bind a Pydantic body and we can inspect Content-Type ourselves).
# This helper does the JSON-vs-multipart branching, JSON-decode-error
# plumbing, and Pydantic→422 conversion identically across milestones,
# activities (all 4 variants), tasks, and subtasks (task-scoped + nested).
# ---------------------------------------------------------------------------
async def dispatch_create(
    request: Request,
    *,
    schema_cls: type[BaseModel],
    json_handler: Callable[..., Any],
    multipart_handler: Callable[..., Awaitable[Any]],
    json_args: tuple = (),
    multipart_args: tuple = (),
):
    """Dispatch a create endpoint between JSON and multipart paths.

    * ``application/json``                 → parse body, validate via
                                             ``schema_cls``, call
                                             ``json_handler(request, *json_args, data)``.
    * ``multipart/form-data`` /
      ``application/x-www-form-urlencoded`` → call
                                             ``multipart_handler(request, *multipart_args)``.

    JSON parse errors and Pydantic ValidationErrors are re-raised as
    FastAPI ``RequestValidationError`` so the framework's built-in 422
    handler renders the standard envelope. Matches the FastAPI behavior
    you'd get if the route were typed ``data: schema_cls`` directly.
    """
    from fastapi.exceptions import RequestValidationError

    content_type = (request.headers.get("content-type") or "").lower()
    if (
        content_type.startswith("multipart/form-data")
        or content_type.startswith("application/x-www-form-urlencoded")
    ):
        return await multipart_handler(request, *multipart_args)

    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        raise RequestValidationError([
            {
                "type": "json_invalid",
                "loc": ("body",),
                "msg": f"Invalid JSON body: {e.msg}",
                "input": None,
            }
        ])
    try:
        data = schema_cls.model_validate(payload)
    except ValidationError as e:
        raise RequestValidationError(e.errors())
    return json_handler(request, *json_args, data)
