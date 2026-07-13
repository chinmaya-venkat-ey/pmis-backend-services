"""OpenAPI ``requestBody`` builders for the dual-mode create endpoints.

Routes that accept BOTH ``application/json`` and ``multipart/form-data``
take ``request: Request`` (so we can sniff Content-Type and dispatch),
which means FastAPI can't auto-generate the Swagger request body. We
attach an explicit ``openapi_extra={"requestBody": ...}`` to each such
route so Swagger UI renders both shapes:

  * JSON: the Pydantic schema (with camelCase aliases via ``model_json_schema``)
  * Multipart: an explicit ``object`` schema listing every form field +
    the ``files`` array (binary).

The multipart properties carry monolith-parity camelCase keys —
``startDate``, ``endDate``, ``vendorIds``, etc. — so the FE submits the
exact same form fields it always has.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel


_MULTIPART_FORMDATA = "multipart/form-data"


def _multipart_string_prop(description: str = "") -> Dict[str, Any]:
    return {"type": "string", "description": description}


def _multipart_datetime_prop(description: str = "") -> Dict[str, Any]:
    return {
        "type": "string",
        "format": "date-time",
        "description": description or "ISO 8601, e.g. 2026-06-01T00:00:00+05:30",
    }


def _multipart_int_prop(description: str = "") -> Dict[str, Any]:
    return {"type": "integer", "minimum": 0, "description": description}


def _multipart_bool_prop(description: str = "") -> Dict[str, Any]:
    return {"type": "boolean", "description": description}


def _multipart_json_array_prop(description: str) -> Dict[str, Any]:
    """Multipart can't carry typed arrays — FE JSON-encodes them as a string."""
    return {"type": "string", "description": description}


def _multipart_files_prop(description: str = "") -> Dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string", "format": "binary"},
        "description": description or (
            "Optional file uploads. Repeat the form key for each file."
        ),
    }


def _multipart_body_prop() -> Dict[str, Any]:
    return {
        "type": "string",
        "description": (
            "Optional inline comment text. When supplied, a comment row is "
            "created against the new entity and any uploaded ``files`` are "
            "bound to that comment (Doc-35 send-event)."
        ),
    }


def dual_mode_request_body(
    json_schema_cls: type[BaseModel],
    *,
    multipart_required: Iterable[str],
    multipart_properties: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the ``openapi_extra={"requestBody": ...}`` envelope for a
    dual-mode create route.

    ``json_schema_cls`` is the Pydantic class for the JSON arm — its
    ``model_json_schema(by_alias=True)`` is used verbatim.

    ``multipart_required`` lists field names that are mandatory on the
    multipart arm. ``multipart_properties`` is the property → schema
    mapping for every form field the route accepts (camelCase keys).
    """
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": json_schema_cls.model_json_schema(by_alias=True),
                },
                _MULTIPART_FORMDATA: {
                    "schema": {
                        "type": "object",
                        "required": list(multipart_required),
                        "properties": multipart_properties,
                    },
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Per-entity multipart property dicts. Each route imports the constant it
# needs and feeds it to ``dual_mode_request_body``.
# ---------------------------------------------------------------------------

PROJECT_MULTIPART_PROPERTIES: Dict[str, Dict[str, Any]] = {
    "name": _multipart_string_prop("Project name (1–255 chars)."),
    "description": _multipart_string_prop("Long-form description."),
    "statusExplanation": _multipart_string_prop(),
    "parentId": _multipart_string_prop("Parent project UUID (optional)."),
    "status": _multipart_string_prop("new / draft / published / closed."),
    "owner": _multipart_string_prop("Division code: tmd1 / tmd2."),
    "category": _multipart_string_prop(),
    "categoryOther": _multipart_string_prop(),
    "categoryOtherReason": _multipart_string_prop(),
    "startDate": _multipart_datetime_prop(),
    "endDate": _multipart_datetime_prop(),
    "vendorIds": _multipart_json_array_prop(
        'JSON-encoded array of vendor UUIDs, e.g. ``["v-uuid-1","v-uuid-2"]``.'
    ),
    "files": _multipart_files_prop(
        "Optional file uploads. Each file is stored as a comment row "
        "with ``body=NULL`` and ``target_kind='project'``."
    ),
}


MILESTONE_MULTIPART_PROPERTIES: Dict[str, Dict[str, Any]] = {
    "name": _multipart_string_prop("Milestone name (1–255 chars)."),
    "description": _multipart_string_prop(),
    "startDate": _multipart_datetime_prop(),
    "endDate": _multipart_datetime_prop(),
    "actualStartDate": _multipart_datetime_prop(
        "Optional. Set when work actually starts."
    ),
    "actualEndDate": _multipart_datetime_prop(
        "Optional. Set when work actually finishes."
    ),
    "position": _multipart_int_prop("Sibling position (1-indexed)."),
    "status": _multipart_string_prop("not_completed / completed (or catalog code)."),
    "priority": _multipart_string_prop(),
    "isResourceBased": _multipart_bool_prop(
        "Mandatory. Resource/man-month driven milestone (true/false)."
    ),
    "isTransactionBased": _multipart_bool_prop(
        "Optional (default false). Per-transaction driven milestone (true/false)."
    ),
    "dependsOn": _multipart_json_array_prop(
        "JSON-encoded array of milestone UUIDs this depends on."
    ),
    "vendors": _multipart_json_array_prop(
        "JSON-encoded array of vendor UUIDs (alias for ``vendorIds``)."
    ),
    "vendorIds": _multipart_json_array_prop(
        "JSON-encoded array of vendor UUIDs."
    ),
    "body": _multipart_body_prop(),
    "files": _multipart_files_prop(),
}


ACTIVITY_MULTIPART_PROPERTIES: Dict[str, Dict[str, Any]] = {
    "name": _multipart_string_prop("Activity name (1–255 chars)."),
    "description": _multipart_string_prop(),
    "startDate": _multipart_datetime_prop(),
    "endDate": _multipart_datetime_prop(),
    "actualStartDate": _multipart_datetime_prop(),
    "actualEndDate": _multipart_datetime_prop(),
    "position": _multipart_int_prop(),
    "status": _multipart_string_prop(),
    "priority": _multipart_string_prop(),
    "ownerDivision": _multipart_string_prop(
        "Division code: tmd1 / tmd2 / others."
    ),
    "concernedDivisions": _multipart_json_array_prop(
        'JSON-encoded array of division codes, e.g. ``["tmd1","tmd2"]``.'
    ),
    "vendorId": _multipart_string_prop("Vendor UUID."),
    "dependsOn": _multipart_json_array_prop(
        "JSON-encoded array of activity UUIDs this depends on."
    ),
    "body": _multipart_body_prop(),
    "files": _multipart_files_prop(),
}


TASK_MULTIPART_PROPERTIES: Dict[str, Dict[str, Any]] = {
    "name": _multipart_string_prop("Task name (1–255 chars)."),
    "description": _multipart_string_prop(),
    "startDate": _multipart_datetime_prop(),
    "endDate": _multipart_datetime_prop(),
    "actualStartDate": _multipart_datetime_prop(),
    "actualEndDate": _multipart_datetime_prop(),
    "position": _multipart_int_prop(),
    "status": _multipart_string_prop(),
    "priority": _multipart_string_prop(),
    "assignedTo": _multipart_string_prop(
        "Assignee user UUID (must satisfy same-vendor + project-membership)."
    ),
    "dependsOn": _multipart_json_array_prop(
        "JSON-encoded array of task UUIDs this depends on."
    ),
    "body": _multipart_body_prop(),
    "files": _multipart_files_prop(),
}


SUBTASK_MULTIPART_PROPERTIES: Dict[str, Dict[str, Any]] = {
    "name": _multipart_string_prop("Subtask name (1–255 chars)."),
    "description": _multipart_string_prop(),
    "startDate": _multipart_datetime_prop(),
    "endDate": _multipart_datetime_prop(),
    "actualStartDate": _multipart_datetime_prop(),
    "actualEndDate": _multipart_datetime_prop(),
    "position": _multipart_int_prop(),
    "status": _multipart_string_prop(),
    "priority": _multipart_string_prop(),
    "assignedTo": _multipart_string_prop(),
    "dependsOn": _multipart_json_array_prop(
        "JSON-encoded array of subtask UUIDs this depends on."
    ),
    "body": _multipart_body_prop(),
    "files": _multipart_files_prop(),
}


# ---------------------------------------------------------------------------
# Multipart-only endpoints (no JSON arm). Used by the per-target attachment
# POSTs and the project-attachments upload route — Swagger UI 5.x renders a
# proper file picker only when we declare ``format: binary`` explicitly.
# ---------------------------------------------------------------------------

def multipart_files_only_request_body(
    *,
    description: str = "One or more files to upload.",
    field_name: str = "files",
) -> Dict[str, Any]:
    """OpenAPI requestBody for a multipart-only upload route.

    ``field_name`` selects the form key Swagger renders. The project
    upload route uses ``"files"`` (plural, repeated array). M/A/T/S
    attachment routes use ``"file"`` (singular, one file) to match
    monolith — the schema in that case is a single ``binary`` string,
    not an array of binaries.
    """
    if field_name == "files":
        prop = _multipart_files_prop(description)
    else:
        prop = {
            "type": "string",
            "format": "binary",
            "description": description,
        }
    return {
        "requestBody": {
            "required": True,
            "content": {
                _MULTIPART_FORMDATA: {
                    "schema": {
                        "type": "object",
                        "required": [field_name],
                        "properties": {
                            field_name: prop,
                        },
                    },
                },
            },
        },
    }


def multipart_body_and_files_request_body(
    *, _description: str = "Comment body and/or files (one required).",  # NOSONAR(S1172): underscore prefix marks intentionally-unused param
) -> Dict[str, Any]:
    """``POST /project/<kind>/{id}/comments`` — body + files multipart shape."""
    return {
        "requestBody": {
            "required": True,
            "content": {
                _MULTIPART_FORMDATA: {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "body": _multipart_body_prop(),
                            "files": _multipart_files_prop(),
                        },
                    },
                },
            },
        },
    }
