"""Dual-mode body helper for the project / milestone / activity / task /
subtask create endpoints — and for the polymorphic comment + attachment
POST endpoints.

Routes accept either ``application/json`` (legacy shape — entity fields
only) or ``multipart/form-data`` (entity fields as form fields plus
optional ``body`` for an inline comment and ``files`` for uploads). When
attachments are present the entity row, the comment row, and the
attachment metadata are persisted in the same request.

Public surface (kept narrow on purpose):

  * ``Multipart422``                  — sentinel exception for parser errors
  * ``parse_form_fields``             — generic form → dict for Pydantic
  * ``extract_files_from_form``       — pull ``files`` uploads out
  * ``pre_validate_files``            — size + extension check pre-DB
  * ``upload_files_via_client``       — write to storage, return URL envelopes
  * ``dispatch_create``               — JSON vs multipart router

The helpers are entity-agnostic — each route supplies its own field spec
(plain strings, ints, JSON-encoded arrays / objects). Mirrors
PMIS-OpenProject/app/api/v3/_inline_attachments.py.
"""
from __future__ import annotations

import json
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
)

from fastapi import Request, UploadFile
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.core.errors import (
    AttachmentDisallowedExtensionError,
    AttachmentTooLargeError,
)
from app.utilities.file_client import StoredFile, get_file_client
from app.utilities.file_signature import detect_and_verify
from app.utilities.file_storage import file_extension
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Sentinel: parser-level rejections (bad int, bad JSON list, bad JSON dict).
# Carries a Pydantic-style ``detail`` so the standard 422 envelope renders.
# ---------------------------------------------------------------------------
class Multipart422(Exception):
    def __init__(self, detail: List[Dict[str, Any]]):
        super().__init__("multipart validation failed")
        self.detail = detail


# ---------------------------------------------------------------------------
# Form-field parser
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
    """Convert a multipart form into a dict ready for Pydantic validation.

    * ``string_keys``           — pass through as strings. Empty strings
                                  are skipped so Swagger UI's blank
                                  auto-fill doesn't fire ``min_length``
                                  validators.
    * ``required_string_keys``  — passed through verbatim (empty strings
                                  stay so Pydantic min_length=1 fires).
    * ``int_keys``              — coerced via ``int(...)``.
    * ``array_keys``            — JSON-decoded; must decode to a list.
    * ``object_keys``           — JSON-decoded; must decode to a dict.

    Raises ``Multipart422`` for parse-level failures; Pydantic catches
    the rest after this returns.
    """
    fields: Dict[str, Any] = {}
    bad: List[Dict[str, Any]] = []

    for key in required_string_keys:
        if key in form:
            v = form[key]
            if isinstance(v, str):
                fields[key] = v

    for key in string_keys:
        if key in form:
            v = form[key]
            if isinstance(v, str):
                if v == "":
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
                    "msg": f"{key} must be a string",
                    "type": "type_error",
                })
                continue
            stripped = raw.strip()
            if not stripped.startswith("["):
                # Plain string (single value) — wrap as single-element list.
                fields[key] = [raw]
                continue
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                bad.append({
                    "loc": ["body", key],
                    "msg": (
                        f"{key} must be a JSON-encoded array string "
                        f"(got {raw!r})"
                    ),
                    "type": "value_error",
                })
                continue
            if not isinstance(decoded, list):
                bad.append({
                    "loc": ["body", key],
                    "msg": f"{key} must decode to a JSON array (got {raw!r})",
                    "type": "type_error",
                })
                continue
            fields[key] = decoded

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
# File helpers
# ---------------------------------------------------------------------------
def extract_files_from_form(form) -> List[UploadFile]:
    """Return every ``files`` entry that has a real filename.

    Swagger UI submits a phantom empty-filename ``files`` entry when the
    user picked nothing — drop those so the empty-multipart case stays
    clean.
    """
    raw = form.getlist("files") if "files" in form else []
    out: List[UploadFile] = []
    for item in raw:
        if hasattr(item, "filename") and item.filename:
            out.append(item)
    return out


def _allowed_extensions() -> set[str]:
    return {
        e.strip().lower().lstrip(".")
        for e in (settings.attachments_allowed_extensions or "").split(",")
        if e.strip()
    }


def _assert_file_size_within_limit(upload: UploadFile, max_bytes: int) -> None:
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    if size > max_bytes:
        raise AttachmentTooLargeError(
            f"File {(upload.filename or 'unnamed')!r} is {size} bytes; "
            f"maximum is {max_bytes}.",
            details={
                "file": upload.filename,
                "size_bytes": size,
                "max_bytes": max_bytes,
            },
        )


def _assert_file_extension_allowed(upload: UploadFile, allowed: set) -> None:
    ext = file_extension(upload.filename or "")
    if not ext or ext not in allowed:
        # Monolith parity: extension rendered with leading dot
        # (``'.exe'`` not ``'exe'``), ``details`` carries only
        # ``file`` + ``extension`` (no ``allowed`` list).
        ext_display = f".{ext}" if ext else "''"
        raise AttachmentDisallowedExtensionError(
            f"File {(upload.filename or 'unnamed')!r} has disallowed "
            f"extension {ext_display!r}. "
            f"Allowed: {', '.join(sorted(allowed))}.",
            details={
                "file": upload.filename,
                "extension": ext,
            },
        )


def _validate_one_upload(
    upload: UploadFile, max_bytes: int, allowed: set,
) -> None:
    """Per-file size + extension + content-magic check chain. Mirrors
    the legacy in-line order: size first, then extension, then magic-
    byte sniff. Extension + magic-byte checks are SKIPPED when the
    allow-list is empty (legacy parity)."""
    _assert_file_size_within_limit(upload, max_bytes)
    if not allowed:
        return
    _assert_file_extension_allowed(upload, allowed)
    # Magic-byte content sniff — rejects disguised binaries (.exe
    # renamed to .pdf etc). Final line of defence after size +
    # extension. Matches monolith parity.
    detect_and_verify(upload.file, upload.filename or "unnamed")


def pre_validate_files(files: List[UploadFile]) -> None:
    """Reject "bad file" cases BEFORE the parent row is inserted.

    Guarantees that a rejected file means no entity was created — the FE
    never has to clean up a half-made milestone / activity / task /
    subtask / project.

    Checks (cheap → expensive):
      1. Per-file size against ``ATTACHMENTS_MAX_BYTES``.
      2. Extension against the allow-list.
      3. Magic-byte content sniff.

    Raises ``AttachmentTooLargeError`` (HTTP 409) or
    ``AttachmentDisallowedExtensionError`` (HTTP 409) on the first failing
    file. Files are checked in caller order; the first failing file's
    error wins.
    """
    if not files:
        return
    allowed = _allowed_extensions()
    max_bytes = settings.attachments_max_bytes
    for upload in files:
        _validate_one_upload(upload, max_bytes, allowed)


def upload_files_via_client(files: List[UploadFile]) -> List[Dict[str, Any]]:
    """Stream each ``UploadFile`` through the file client and return the
    list of attachment envelopes ready to persist on a comment row.

    On the first storage failure the helper best-effort deletes any
    already-uploaded files in this batch and re-raises — so the comment
    row never ends up pointing at half-written bytes.
    """
    if not files:
        return []
    client = get_file_client()
    written: List[StoredFile] = []
    try:
        for upload in files:
            stored = client.upload(
                file_obj=upload.file,
                original_filename=upload.filename or "unnamed",
                mime_type=upload.content_type or "application/octet-stream",
            )
            written.append(stored)
    except Exception:
        for s in written:
            try:
                client.delete(s.storage_key)
            except Exception:  # noqa: BLE001 — best-effort cleanup
                logger.warning(
                    "Failed to clean up partial upload %s after error",
                    s.storage_key,
                )
        raise
    # Monolith parity: ``uploadedAt`` is serialised in IST (``+05:30``)
    # so the wire matches the rest of the timestamp fields. The
    # file-client stamps ``uploaded_at`` in UTC; we coerce here at the
    # envelope boundary.
    from app.utilities.timezones import iso_ist
    return [
        {
            "url": s.url,
            "filename": s.filename,
            "mimeType": s.mime_type,
            "sizeBytes": s.size_bytes,
            "uploadedAt": iso_ist(s.uploaded_at),
        }
        for s in written
    ]


# ---------------------------------------------------------------------------
# Route-layer dispatch helper
# ---------------------------------------------------------------------------
async def dispatch_create(
    request: Request,
    *,
    schema_cls: type[BaseModel],
    json_handler: Callable[[BaseModel], Any],
    multipart_handler: Callable[[], Awaitable[Any]],
):
    """Dispatch a create endpoint between JSON and multipart paths.

    * ``application/json``  → parse body, validate via ``schema_cls``,
      call ``json_handler(parsed_model)``.
    * ``multipart/form-data`` / ``application/x-www-form-urlencoded`` →
      call ``await multipart_handler()``.

    JSON parse errors and Pydantic ValidationError are re-raised as
    FastAPI ``RequestValidationError`` so the framework's built-in 422
    handler renders the standard envelope — matches the behavior of a
    route typed ``data: schema_cls`` directly.
    """
    from fastapi.exceptions import RequestValidationError

    content_type = (request.headers.get("content-type") or "").lower()
    if (
        content_type.startswith("multipart/form-data")
        or content_type.startswith("application/x-www-form-urlencoded")
    ):
        return await multipart_handler()

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
    return json_handler(data)
