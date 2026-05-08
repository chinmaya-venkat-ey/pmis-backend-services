"""Generate Postman v2.1 collection from FastAPI's OpenAPI schema.

Usage (from user-mgmt repo root, with venv active):
    python scripts/generate_postman_collection.py

Reads the live FastAPI app (no need to start uvicorn — just imports it),
calls ``app.openapi()`` to get the OpenAPI spec, and converts it to a
Postman v2.1 collection that's written to
``PMIS_User_Service.postman_collection.json`` at the repo root.

Run this whenever the API surface changes — adds/renames/removes
endpoints, request/response schema changes, etc. The output is
deterministic: same code → same collection.

Variables in the collection:
    {{baseUrl}}      — root URL, default http://127.0.0.1:8001
    {{accessToken}}  — Bearer token, set after calling /login
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.main import app  # noqa: E402


# ---- OpenAPI schema → example value -------------------------------------


def _resolve_ref(ref: str, components: Dict[str, Any]) -> Dict[str, Any]:
    name = ref.replace("#/components/schemas/", "")
    return components.get("schemas", {}).get(name, {})


def _example_for_schema(schema: Dict[str, Any], components: Dict[str, Any]) -> Any:
    """Best-effort example value for a JSON-schema fragment."""
    if not schema:
        return None
    if "$ref" in schema:
        return _example_for_schema(_resolve_ref(schema["$ref"], components), components)
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "anyOf" in schema:
        # Prefer the first non-null option.
        for opt in schema["anyOf"]:
            if opt.get("type") != "null":
                return _example_for_schema(opt, components)
        return None
    if "oneOf" in schema:
        return _example_for_schema(schema["oneOf"][0], components)
    if "allOf" in schema:
        merged: Dict[str, Any] = {}
        for part in schema["allOf"]:
            resolved = part if "$ref" not in part else _resolve_ref(part["$ref"], components)
            for k, v in (resolved.get("properties") or {}).items():
                merged.setdefault(k, v)
        return {k: _example_for_schema(v, components) for k, v in merged.items()}

    enum = schema.get("enum")
    if enum:
        return enum[0]

    fmt = schema.get("format")
    schema_type = schema.get("type")

    if schema_type == "string" or "format" in schema:
        if fmt == "email":
            return "user@example.com"
        if fmt == "date-time":
            return "2026-01-01T00:00:00Z"
        if fmt == "date":
            return "2026-01-01"
        if fmt == "uuid":
            return "00000000-0000-0000-0000-000000000000"
        return ""
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return False
    if schema_type == "array":
        return [_example_for_schema(schema.get("items", {}), components)]
    if schema_type == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        return {k: _example_for_schema(v, components) for k, v in props.items()}

    return None


# ---- OpenAPI operation → Postman item -----------------------------------


def _path_to_postman_url(path: str) -> Dict[str, Any]:
    """Turn '/api/v3/users/{user_id}' into a Postman url object."""
    raw_path = "{{baseUrl}}" + path
    parts = [p for p in path.split("/") if p]
    # Postman uses :var for path variables, not {var}.
    postman_parts = [
        f":{p[1:-1]}" if p.startswith("{") and p.endswith("}") else p
        for p in parts
    ]
    return {
        "raw": raw_path,
        "host": ["{{baseUrl}}"],
        "path": postman_parts,
    }


def _build_request(
    method: str,
    path: str,
    operation: Dict[str, Any],
    components: Dict[str, Any],
    is_protected: bool,
) -> Dict[str, Any]:
    headers: List[Dict[str, str]] = []
    request: Dict[str, Any] = {
        "method": method.upper(),
        "header": headers,
        "url": _path_to_postman_url(path),
    }

    description = operation.get("description") or operation.get("summary")
    if description:
        request["description"] = description.strip()

    if is_protected:
        headers.append({
            "key": "Authorization",
            "value": "Bearer {{accessToken}}",
            "type": "text",
        })

    # Body for write methods.
    if method.lower() in {"post", "put", "patch"}:
        request_body = operation.get("requestBody") or {}
        content = (request_body.get("content") or {}).get("application/json", {})
        body_schema = content.get("schema")
        if body_schema is not None:
            example = _example_for_schema(body_schema, components)
            if example is not None:
                headers.append({
                    "key": "Content-Type",
                    "value": "application/json",
                    "type": "text",
                })
                request["body"] = {
                    "mode": "raw",
                    "raw": json.dumps(example, indent=2, default=str),
                    "options": {"raw": {"language": "json"}},
                }

    # Path / query parameters.
    parameters = operation.get("parameters") or []
    path_vars: List[Dict[str, str]] = []
    query: List[Dict[str, Any]] = []
    for param in parameters:
        loc = param.get("in")
        name = param.get("name")
        if not name:
            continue
        param_schema = param.get("schema") or {}
        sample = _example_for_schema(param_schema, components)
        if sample is None:
            sample = ""
        if loc == "path":
            path_vars.append({
                "key": name,
                "value": str(sample),
                "description": (param.get("description") or "").strip(),
            })
        elif loc == "query":
            query.append({
                "key": name,
                "value": str(sample),
                "description": (param.get("description") or "").strip(),
                "disabled": not param.get("required", False),
            })

    if path_vars:
        request["url"]["variable"] = path_vars
    if query:
        request["url"]["query"] = query

    return request


def _slugify_tag(tag: str) -> str:
    """Map an OpenAPI tag to a friendlier folder name."""
    overrides = {
        "users": "Authentication & Users",
        "health": "Health & Root",
        "catalogs": "Catalogs",
        "projects": "Projects",
        "milestones": "Milestones",
        "activities": "Activities",
        "tasks": "Tasks",
        "subtasks": "Subtasks",
        "meetings": "Meetings",
        "vendors": "Vendors",
        "resource_types": "Resource Types",
        "resource-types": "Resource Types",
        "roles": "Roles",
        "work_packages": "Work Packages",
        "work-packages": "Work Packages",
        "work_package_types": "Work Package Types",
        "project_members": "Project Members",
        "tree": "Project Tree",
    }
    return overrides.get(tag, tag.replace("_", " ").replace("-", " ").title())


# ---- Top-level conversion ----------------------------------------------


def build_collection() -> Dict[str, Any]:
    schema = app.openapi()
    components = schema.get("components") or {}
    info = schema.get("info") or {}

    folders: Dict[str, Dict[str, Any]] = {}

    for path, path_item in (schema.get("paths") or {}).items():
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            tags = operation.get("tags") or ["Untagged"]
            primary_tag = tags[0]
            folder_name = _slugify_tag(primary_tag)
            folder = folders.setdefault(folder_name, {"name": folder_name, "item": []})

            is_protected = bool(operation.get("security"))
            request = _build_request(
                method, path, operation, components, is_protected,
            )

            name = operation.get("summary") or f"{method.upper()} {path}"
            folder["item"].append({
                "name": name,
                "request": request,
                "response": [],
            })

    # Sort folders by name; sort items inside each folder by name.
    sorted_items = []
    for name in sorted(folders.keys()):
        folder = folders[name]
        folder["item"].sort(key=lambda x: x["name"])
        sorted_items.append(folder)

    return {
        "info": {
            "_postman_id": str(uuid.uuid4()),
            "name": info.get("title") or "PMIS API",
            "description": (
                f"{info.get('description', '')}\n\n"
                f"Auto-generated from FastAPI OpenAPI by "
                f"scripts/generate_postman_collection.py. "
                f"Re-run that script after API changes."
            ).strip(),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": sorted_items,
        "variable": [
            {
                "key": "baseUrl",
                "value": "http://127.0.0.1:8001",
                "type": "string",
                "description": "Root URL of the user-management service. Override per environment.",
            },
            {
                "key": "accessToken",
                "value": "",
                "type": "string",
                "description": "Bearer token. Set after calling Login.",
            },
        ],
    }


def main() -> None:
    collection = build_collection()
    out = REPO_ROOT / "PMIS_User_Service.postman_collection.json"
    out.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    total = sum(len(folder["item"]) for folder in collection["item"])
    print(f"Wrote {out}")
    print(f"  {len(collection['item'])} folders, {total} requests")


if __name__ == "__main__":
    main()
