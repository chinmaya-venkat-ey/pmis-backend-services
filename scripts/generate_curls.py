"""Generate a flat ``POSTMAN_CURLS.md`` of copy-paste curls from the
generated Postman collection.

Reads ``PMIS_User_Service.postman_collection.json`` (sibling of this
repo root), walks the folder/item tree, emits one curl per request
into a markdown file grouped by folder. Variables ``{{baseUrl}}``,
``{{accessToken}}``, and path placeholders (``:user_id`` etc.) are
left as-is so they're trivial to find-replace.

Run after ``scripts/generate_postman_collection.py`` so the curls
match the live OpenAPI surface. The two outputs sit side-by-side at
the repo root.

Usage:
    python scripts/generate_curls.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLECTION = REPO_ROOT / "PMIS_User_Service.postman_collection.json"
OUTPUT = REPO_ROOT / "POSTMAN_CURLS.md"

# ---------------------------------------------------------------------------
# Sample-value substitution. Goal: every curl is copy-paste-runnable
# with sensible defaults. Dynamic values that MUST come from a prior
# response (ephemeral_token, refresh_token, dynamic assignment_id) stay
# as ``<UPPERCASE>`` placeholders so the user knows to swap them.
# ---------------------------------------------------------------------------

# Replace literal Postman variables in URLs.
URL_VAR_DEFAULTS = {
    "{{baseUrl}}": "http://10.1.131.199:8001",
    "{{accessToken}}": "<ACCESS_TOKEN>",
}

# Path placeholders (`:user_id`, `:role_id`, …). Values picked from
# real seeded data on the dev server: bootstrap admin user, "role org"
# vendor, "ey app" published project, `admin` role (id 12).
PATH_VAR_DEFAULTS = {
    "user_id": "94eeede1-c925-44ad-8de6-416dc87b5999",  # bootstrap admin
    "target_id": "94eeede1-c925-44ad-8de6-416dc87b5999",
    "role_id": "12",                                      # admin role
    "role_name": "admin",
    "vendor_id": "7f9ec285-5a94-4d2f-9d2c-a248d302b1c5",  # role org
    "project_uuid": "a278f77b-a2ef-4797-b4fa-ac3fe82e7037",  # ey app
    "project_id": "a278f77b-a2ef-4797-b4fa-ac3fe82e7037",
    "code": "users:read",
    "permission_code": "users:read",
    "assignment_id": "<ASSIGNMENT_ID>",
    "milestone_id": "<MILESTONE_ID>",
    "activity_id": "<ACTIVITY_ID>",
    "task_id": "<TASK_ID>",
    "subtask_id": "<SUBTASK_ID>",
    "parent_subtask_id": "<PARENT_SUBTASK_ID>",
    "comment_id": "<COMMENT_ID>",
    "attachment_id": "<ATTACHMENT_ID>",
    "membership_id": "<MEMBERSHIP_ID>",
    "transition_id": "<TRANSITION_ID>",
    "division_id": "<DIVISION_ID>",
    "resource_type_id": "<RESOURCE_TYPE_ID>",
    "id": "<ID>",
}

# Body field defaults — flat key → value lookup. Walks every JSON
# object in the body and fills empty / placeholder values per this map.
BODY_FIELD_DEFAULTS = {
    # ---- auth ----
    "login": "your_login",
    "login_or_email": "your_login",
    "password": "Pmis@1234",
    "new_password": "Pmis@1234",
    "ephemeral_token": "<EPHEMERAL_TOKEN>",
    "code": "000000",
    "channel": "email",
    "token_or_code": "<TOKEN_OR_CODE>",
    "access_token": "<ACCESS_TOKEN>",
    "refresh_token": "<REFRESH_TOKEN>",

    # ---- user / vendor common ----
    "email": "user@example.com",
    "firstName": "John",
    "lastName": "Doe",
    "phoneNumber": "+919999999999",
    "phone_number": "+919999999999",
    "admin": False,
    "status": "active",
    "vendorId": "7f9ec285-5a94-4d2f-9d2c-a248d302b1c5",
    "vendor_id": "7f9ec285-5a94-4d2f-9d2c-a248d302b1c5",
    "division": "tmd1",
    "divisionOther": None,
    "division_other": None,
    "orgRole": "project_member",
    "name": "Sample Name",
    "description": "Sample description",
    "active": True,
    "contactPerson": "Jane Doe",
    "contact_person": "Jane Doe",

    # ---- ids & references ----
    "userId": "94eeede1-c925-44ad-8de6-416dc87b5999",
    "user_id": "94eeede1-c925-44ad-8de6-416dc87b5999",
    "roleId": 12,
    "role_id": 12,
    "projectId": "a278f77b-a2ef-4797-b4fa-ac3fe82e7037",
    "project_id": "a278f77b-a2ef-4797-b4fa-ac3fe82e7037",
    "organizationId": "7f9ec285-5a94-4d2f-9d2c-a248d302b1c5",
    "organization_id": "7f9ec285-5a94-4d2f-9d2c-a248d302b1c5",
    "role": "project_member",

    # ---- catalog rows ----
    "label": "Sample Label",
    "requiresOther": False,
    "requires_other": False,
}

# When the schema gives a List[X] sample with a single placeholder
# entry, fill the entry with a sensible value where we have a default
# for that element shape.
LIST_FIELD_DEFAULTS = {
    "project_ids": ["a278f77b-a2ef-4797-b4fa-ac3fe82e7037"],
    "projectIds": ["a278f77b-a2ef-4797-b4fa-ac3fe82e7037"],
    "user_ids": ["94eeede1-c925-44ad-8de6-416dc87b5999"],
    "userIds": ["94eeede1-c925-44ad-8de6-416dc87b5999"],
    "permissions": ["users:read"],
    # projectAssignments + assignments stay as a single sample dict;
    # the dict's interior fields are filled by BODY_FIELD_DEFAULTS.
}


def _fill_body(value: Any, key_hint: str | None = None) -> Any:
    """Recursively walk a parsed JSON body and substitute sample values.

    The key_hint is the field name from the parent object — used so we
    can fill ``"login": ""`` based on the key, not the empty value.
    """
    if isinstance(value, dict):
        return {k: _fill_body(v, key_hint=k) for k, v in value.items()}
    if isinstance(value, list):
        # Whole-list override (e.g., project_ids → list of UUIDs).
        if key_hint in LIST_FIELD_DEFAULTS:
            return list(LIST_FIELD_DEFAULTS[key_hint])
        # Otherwise recurse into each entry.
        return [_fill_body(v) for v in value]
    # Leaf: fill if the field name is known AND the existing value is
    # the OpenAPI-generator sentinel (empty string, 0, etc.).
    if key_hint in BODY_FIELD_DEFAULTS:
        is_empty_string = isinstance(value, str) and value == ""
        is_zero = value == 0 or value is False
        is_none = value is None
        # Always override known fields. The OpenAPI generator tends to
        # emit empty strings; we replace them with sensible defaults.
        if is_empty_string or is_none or is_zero or value == "user@example.com":
            return BODY_FIELD_DEFAULTS[key_hint]
    return value


def _flatten_items(items: List[dict], parent_path: Tuple[str, ...] = ()) -> Iterable[Tuple[Tuple[str, ...], dict]]:
    """Yield (folder_path, request_item) pairs for every leaf item."""
    for it in items:
        if "item" in it:
            yield from _flatten_items(it["item"], parent_path + (it["name"],))
        elif "request" in it:
            yield parent_path, it


def _substitute_url(url_raw: str) -> str:
    """Apply URL_VAR_DEFAULTS + PATH_VAR_DEFAULTS to a Postman raw URL."""
    out = url_raw
    for var, val in URL_VAR_DEFAULTS.items():
        out = out.replace(var, val)
    # Postman raw URLs use ``{path_var}`` while path arrays use ``:path_var``.
    for var, val in PATH_VAR_DEFAULTS.items():
        out = out.replace("{" + var + "}", val)
    return out


def _substitute_header(value: str) -> str:
    out = value
    for var, val in URL_VAR_DEFAULTS.items():
        out = out.replace(var, val)
    return out


def _substitute_body(raw: str) -> str:
    """Parse the raw JSON body, fill sample values, and re-serialize.

    Falls back to the original raw text if parsing fails (e.g. a body
    that isn't valid JSON for some reason)."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    filled = _fill_body(parsed)
    return json.dumps(filled, indent=2)


def _curl_for(item: dict) -> str:
    """Build a single multi-line curl command with sample values filled in.

    Postman placeholders ({{baseUrl}}, path vars) are substituted from
    URL_VAR_DEFAULTS / PATH_VAR_DEFAULTS. Body fields are filled from
    BODY_FIELD_DEFAULTS / LIST_FIELD_DEFAULTS. Auth headers stay as
    ``<ACCESS_TOKEN>`` for the user to paste a fresh JWT.
    """
    req = item["request"]
    method = req.get("method", "GET").upper()
    url_raw = _substitute_url(req.get("url", {}).get("raw", ""))

    parts: List[str] = [f"curl -X {method} '{url_raw}'"]
    for h in req.get("header", []) or []:
        if h.get("disabled"):
            continue
        key = h.get("key", "")
        val = _substitute_header(h.get("value", ""))
        # Escape single quotes in header values.
        val_safe = val.replace("'", "'\\''")
        parts.append(f"  -H '{key}: {val_safe}'")

    body = req.get("body") or {}
    if body.get("mode") == "raw":
        raw = body.get("raw", "")
        if raw:
            filled = _substitute_body(raw)
            body_safe = filled.replace("'", "'\\''")
            parts.append(f"  -d '{body_safe}'")

    return " \\\n".join(parts)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_ " else "-" for c in text).strip()


def main() -> None:
    if not COLLECTION.exists():
        raise SystemExit(
            f"{COLLECTION.name} not found in {REPO_ROOT}. "
            "Run scripts/generate_postman_collection.py first."
        )

    data = json.loads(COLLECTION.read_text(encoding="utf-8"))
    name = data.get("info", {}).get("name", "API")
    desc = data.get("info", {}).get("description", "")

    out: List[str] = []
    out.append(f"# {name} — direct curls\n")
    out.append(
        "> Auto-generated by `scripts/generate_curls.py` from "
        f"`{COLLECTION.name}`. Re-run after the Postman collection is "
        "regenerated so this file stays in sync.\n"
    )
    if desc:
        out.append(f"\n{desc}\n")
    out.append(
        "\n## How to use\n\n"
        "Sample values are pre-filled — most curls run as-is once you "
        "paste a fresh `<ACCESS_TOKEN>`. Keep the placeholders below "
        "in mind:\n\n"
        "- **`<ACCESS_TOKEN>`** — bearer JWT. Get one from the login "
        "flow (`Authenticate user` → `Send OTP for 2FA login` → "
        "`Verify OTP and complete login`). On the dev server the "
        "universal OTP is `000000`. Tokens last ~15 min.\n"
        "- **`<EPHEMERAL_TOKEN>`**, **`<TOKEN_OR_CODE>`**, "
        "**`<REFRESH_TOKEN>`** — come from a prior response in the "
        "auth flow. Substitute on each call.\n"
        "- **`<ASSIGNMENT_ID>`**, **`<MILESTONE_ID>`**, etc. — IDs "
        "the curl can't know up-front. Hit the relevant `GET /list` "
        "first and paste an ID from the response.\n\n"
        "Pre-filled sample IDs use real seeded data on the dev server "
        "(`http://10.1.131.199`):\n"
        "- bootstrap admin user `94eeede1-c925-44ad-8de6-416dc87b5999`,\n"
        "- vendor `7f9ec285-5a94-4d2f-9d2c-a248d302b1c5` (\"role org\"),\n"
        "- published project `a278f77b-a2ef-4797-b4fa-ac3fe82e7037` (\"ey app\"),\n"
        "- `admin` role id `12`.\n\n"
        "**Windows PowerShell**: swap single-quoted bodies for double-"
        "quoted with escaped inner quotes, or run the curls from Git "
        "Bash / WSL where the quoting works verbatim.\n\n"
        "---\n"
    )

    # Group leaves by their immediate parent folder.
    by_folder: dict[str, List[dict]] = {}
    for parent, item in _flatten_items(data.get("item", [])):
        folder = " / ".join(parent) if parent else "(top-level)"
        by_folder.setdefault(folder, []).append(item)

    # Sort folders for stable output.
    for folder in sorted(by_folder.keys()):
        out.append(f"\n## {folder}\n")
        for item in sorted(by_folder[folder], key=lambda it: it["name"]):
            req_name = item["name"]
            method = item["request"].get("method", "GET").upper()
            url_raw = item["request"].get("url", {}).get("raw", "")
            req_desc = item["request"].get("description", "").strip()

            out.append(f"\n### {method} — {req_name}\n")
            out.append(f"`{method} {url_raw}`\n")
            if req_desc:
                # Keep description short; one paragraph max.
                first_para = req_desc.split("\n\n", 1)[0]
                out.append(f"\n{first_para}\n")
            out.append("\n```bash\n")
            out.append(_curl_for(item))
            out.append("\n```\n")

    OUTPUT.write_text("".join(out), encoding="utf-8")
    n_requests = sum(len(v) for v in by_folder.values())
    print(f"Wrote {OUTPUT}")
    print(f"  {len(by_folder)} folders, {n_requests} requests")


if __name__ == "__main__":
    main()
