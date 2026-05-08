"""
HAL+JSON response formatter for OpenProject API v3 compliance.
"""
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel
from fastapi.responses import JSONResponse

class Link(BaseModel):
    """HAL link representation."""
    href: str
    title: Optional[str] = None


class HalResponse(BaseModel):
    """Base HAL+JSON response structure."""
    _type: str
    _links: Dict[str, Union[Link, Dict[str, str]]]
    _embedded: Optional[Dict[str, Any]] = None


def format_user_response(
    user_data: Dict[str, Any],
    base_url: str = "/api/v3",
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    """Format a single user response in HAL+JSON format.

    Embeds the slim vendor object (when present), the division enum +
    its free-text override (when 'others'), and the user's mapped
    projects (filtered for live + non-closed by the repository).

    Doc 44: when ``db`` is supplied, the response also carries the
    FE-friendly role projection — ``orgRole`` (the user's highest tier
    among the 5 FE-known roles), ``vendorId`` (flat alias of
    ``vendor.id``), and a ``role`` field on each project entry.
    Callers that don't have a session handy (legacy code, tests)
    omit ``db`` and the projection is silently skipped.
    """
    user_id = user_data.get("id")

    # Vendor: embed { id, name } when the user is mapped, else None.
    vendor_id = user_data.get("vendor_id")
    vendor_block = None
    if vendor_id:
        vendor_block = {
            "id": vendor_id,
            "name": user_data.get("vendor_name"),
        }

    # Doc 44 role projection: precompute the per-project role map so
    # we can surface it on each project entry below. Skipped if no db
    # session was passed (legacy callers).
    project_role_map: Dict[str, str] = {}
    org_role: Optional[str] = None
    if db is not None and user_id:
        from ..infrastructure.db.repositories.rbac_repository import (
            RbacRepository,
        )
        repo = RbacRepository(db)
        org_role = repo.derive_org_role(user_id)
        project_role_map = repo.get_project_role_map(user_id)

    # Mapped projects (slim). Doc 44 attaches the user's role on each
    # project when the role projection is available.
    projects_block = []
    for p in (user_data.get("projects") or []):
        entry = {
            "id": p.get("id"),
            "projectCode": p.get("project_code"),
            "name": p.get("name"),
            "status": p.get("status"),
        }
        if project_role_map:
            entry["role"] = project_role_map.get(p.get("id"))
        projects_block.append(entry)

    response = {
        "_type": "User",
        "_links": {
            "self": {
                "href": f"{base_url}/users/{user_id}",
                "title": user_data.get("login"),
            }
        },
        "id": user_id,
        # Doc 25: human-readable display identifier (US-XXXX-YYMMDDHHMMSS).
        # Coexists with ``id`` (the integer) — the FE prefers ``userCode``
        # for display / search, ``id`` for FK / cross-references.
        "userCode": user_data.get("user_code"),
        "login": user_data.get("login"),
        "firstName": user_data.get("first_name"),
        "lastName": user_data.get("last_name"),
        "email": user_data.get("email"),
        "admin": user_data.get("admin", False),
        "status": user_data.get("status", "active"),
        "vendor": vendor_block,
        # Doc 44: flat alias of vendor.id so the FE can read it without
        # destructuring the embedded vendor object. Always emitted
        # (None when the user has no vendor mapping).
        "vendorId": vendor_id,
        "division": user_data.get("division"),
        "divisionOther": user_data.get("division_other"),
        "phoneNumber": user_data.get("phone_number"),
        "projects": projects_block,
        # Doc 44: single FE-friendly role label. None when the user
        # holds no role known to the FE (e.g. only division_member,
        # or no role at all).
        "orgRole": org_role,
        "createdAt": user_data.get("created_at"),
        "updatedAt": user_data.get("updated_at"),
        "deletedAt": user_data.get("deleted_at"),
        "deletedBy": user_data.get("deleted_by"),
    }

    return response


def format_collection_response(
    items: List[Dict[str, Any]],
    total: int,
    page: int,
    page_size: int,
    base_url: str = "/api/v3",
    collection_type: str = "users"
) -> Dict[str, Any]:
    """
    Format a collection response in HAL+JSON format with pagination.

    Args:
        items: List of items to include
        total: Total number of items
        page: Current page number (1-indexed)
        page_size: Number of items per page
        base_url: Base API URL
        collection_type: Type of collection (e.g., 'users', 'projects')

    Returns:
        HAL+JSON formatted collection response
    """
    # Sanitize pagination inputs to avoid division by zero and invalid pages
    if page_size is None or page_size <= 0:
        page_size = 20

    if page is None or page < 1:
        page = 1

    # Compute total pages safely (if total == 0, treat as single empty page)
    if total > 0:
        total_pages = (total + page_size - 1) // page_size
    else:
        total_pages = 1

    # Build pagination links
    links = {
        "self": {"href": f"{base_url}/{collection_type}?offset={page}&pageSize={page_size}"}
    }

    if page > 1:
        links["first"] = {"href": f"{base_url}/{collection_type}?offset=1&pageSize={page_size}"}
        links["prev"] = {"href": f"{base_url}/{collection_type}?offset={page - 1}&pageSize={page_size}"}

    if page < total_pages:
        links["next"] = {"href": f"{base_url}/{collection_type}?offset={page + 1}&pageSize={page_size}"}
        links["last"] = {"href": f"{base_url}/{collection_type}?offset={total_pages}&pageSize={page_size}"}

    # Format embedded items based on collection type
    if collection_type == "users":
        formatted_items = [format_user_response(item, base_url) for item in items]
    elif collection_type == "projects":
        formatted_items = [format_project_response(item, base_url) for item in items]
    elif collection_type == "roles":
        formatted_items = [format_role_response(item, base_url) for item in items]
    else:
        formatted_items = items

    response = {
        "_type": "Collection",
        "_links": links,
        "total": total,
        "count": len(items),
        "pageSize": page_size,
        "offset": page,
        "_embedded": {
            "elements": formatted_items
        }
    }

    return response


def format_project_response(
    project_data: Dict[str, Any],
    base_url: str = "/api/v3"
) -> Dict[str, Any]:
    """
    Format a single project response in HAL+JSON format.

    Args:
        project_data: Project data dictionary
        base_url: Base API URL

    Returns:
        HAL+JSON formatted response
    """
    project_id = project_data.get("id")
    project_code = project_data.get("project_code")

    # URLs use id (UUID string — the public handle).
    self_href = f"{base_url}/projects/{project_id}" if project_id else None

    response = {
        "_type": "Project",
        "_links": {
            "self": {
                "href": self_href,
                "title": project_data.get("name")
            }
        },
        "id": project_id,
        "projectCode": project_code,
        "name": project_data.get("name"),
        "description": project_data.get("description"),
        "active": project_data.get("active", True),
        "public": project_data.get("public", False),
        "isPublic": project_data.get("public", False),
        "statusExplanation": project_data.get("status_explanation"),
        "status": project_data.get("status"),
        "owner": project_data.get("owner"),
        "ownerOther": project_data.get("owner_other"),
        "category": project_data.get("category"),
        "categoryOther": project_data.get("category_other"),
        "categoryOtherReason": project_data.get("category_other_reason"),
        "vendors": project_data.get("vendors", []),
        "startDate": project_data.get("start_date"),
        "endDate": project_data.get("end_date"),
        "actualStartDate": project_data.get("actual_start_date"),
        "actualEndDate": project_data.get("actual_end_date"),
        # Doc 33: ``isVersion`` / ``versionOf`` / ``baselineId`` /
        # ``versionNo`` removed from the response with the versioning
        # feature.
        "parentId": project_data.get("parent_id"),
        "createdBy": project_data.get("created_by"),
        "updatedBy": project_data.get("updated_by"),
        "createdAt": project_data.get("created_at"),
        "updatedAt": project_data.get("updated_at"),
        # Soft-delete marker. NULL on live projects; set on rows surfaced by
        # the GET /projects/all endpoint.
        "deletedAt": project_data.get("deleted_at"),
        "deletedBy": project_data.get("deleted_by"),
    }

    # Parent link derived from the UUID we emit above.
    parent_id = project_data.get("parent_id")
    if parent_id:
        response["_links"]["parent"] = {
            "href": f"{base_url}/projects/{parent_id}"
        }

    return response


# Doc 44 — display labels for the FE role-name dropdown. Keys are the
# canonical (snake_case) role names; values are the human-readable
# Title Case forms the FE expects to surface in pickers and to read
# back in projectAssignments[].role.
_ROLE_DISPLAY_NAMES: Dict[str, str] = {
    "super_admin":      "Super Admin",
    "admin":            "Admin",
    "org_admin":        "Organization Admin",
    "project_admin":    "Project Admin",
    "project_member":   "Project Member",
    "division_member":  "Division Member",
}


def _role_display_name(name: Optional[str]) -> Optional[str]:
    """Title-case display label for built-in roles; falls back to a
    naive Title Case for custom roles so the FE always has something
    presentable in dropdowns."""
    if not name:
        return None
    if name in _ROLE_DISPLAY_NAMES:
        return _ROLE_DISPLAY_NAMES[name]
    return name.replace("_", " ").replace("-", " ").title()


def format_role_response(
    role_data: Dict[str, Any],
    base_url: str = "/api/v3"
) -> Dict[str, Any]:
    """
    Format a single role response in HAL+JSON format.

    Args:
        role_data: Role data dictionary
        base_url: Base API URL

    Returns:
        HAL+JSON formatted response
    """
    role_id = role_data.get("id")
    name = role_data.get("name")

    response = {
        "_type": "Role",
        "_links": {
            "self": {
                "href": f"{base_url}/roles/{role_id}",
                "title": name,
            }
        },
        "id": role_id,
        "name": name,
        # Doc 44: human-readable label the FE renders in dropdowns +
        # echoes back in projectAssignments[].role.
        "displayName": _role_display_name(name),
        "description": role_data.get("description"),
        "permissions": role_data.get("permissions", []),
        "builtin": role_data.get("builtin", False),
        "createdAt": role_data.get("created_at"),
        "updatedAt": role_data.get("updated_at"),
    }

    return response


def format_meeting_response(
    meeting_data: Dict[str, Any],
    base_url: str = "/api/v3"
) -> Dict[str, Any]:
    """
    Format a single meeting response in HAL+JSON format.

    Args:
        meeting_data: Meeting data dictionary
        base_url: Base API URL

    Returns:
        HAL+JSON formatted response
    """
    meeting_id = meeting_data.get("id")
    project_id = meeting_data.get("project_id")

    response = {
        "_type": "Meeting",
        "_links": {
            "self": {
                "href": f"{base_url}/meetings/{meeting_id}",
                "title": meeting_data.get("title")
            },
            "project": {
                "href": f"{base_url}/projects/{project_id}"
            }
        },
        "id": meeting_id,
        "title": meeting_data.get("title"),
        "description": meeting_data.get("description"),
        "scheduledAt": meeting_data.get("scheduled_at"),
        "durationMinutes": meeting_data.get("duration_minutes"),
        "location": meeting_data.get("location"),
        "createdBy": meeting_data.get("created_by_id"),
        "createdAt": meeting_data.get("created_at"),
        "updatedAt": meeting_data.get("updated_at"),
    }

    return response


def format_meeting_participant_response(
    participant_data: Dict[str, Any],
    base_url: str = "/api/v3"
) -> Dict[str, Any]:
    """
    Format a meeting participant response in HAL+JSON format.

    Args:
        participant_data: Participant data dictionary
        base_url: Base API URL

    Returns:
        HAL+JSON formatted response
    """
    participant_id = participant_data.get("id")
    user_id = participant_data.get("user_id")

    response = {
        "_type": "MeetingParticipant",
        "_links": {
            "self": {
                "href": f"{base_url}/participants/{participant_id}"
            },
            "user": {
                "href": f"{base_url}/users/{user_id}"
            }
        },
        "id": participant_id,
        "userId": user_id,
        "createdAt": participant_data.get("created_at"),
    }

    return response


def format_agenda_item_response(
    agenda_item_data: Dict[str, Any],
    base_url: str = "/api/v3"
) -> Dict[str, Any]:
    """
    Format an agenda item response in HAL+JSON format.

    Args:
        agenda_item_data: Agenda item data dictionary
        base_url: Base API URL

    Returns:
        HAL+JSON formatted response
    """
    agenda_item_id = agenda_item_data.get("id")
    meeting_id = agenda_item_data.get("meeting_id")
    project_id = agenda_item_data.get("project_id")

    response = {
        "_type": "AgendaItem",
        "_links": {
            "self": {
                "href": f"{base_url}/agenda_items/{agenda_item_id}"
            },
            "meeting": {
                "href": f"{base_url}/meetings/{meeting_id}"
            },
            "project": {
                "href": f"{base_url}/projects/{project_id}"
            }
        },
        "id": agenda_item_id,
        "title": agenda_item_data.get("title"),
        "description": agenda_item_data.get("description"),
        "position": agenda_item_data.get("position"),
        "createdAt": agenda_item_data.get("created_at"),
        "updatedAt": agenda_item_data.get("updated_at"),
    }

    # Add work package link if present
    if agenda_item_data.get("work_package_id"):
        response["_links"]["workPackage"] = {
            "href": f"{base_url}/work_packages/{agenda_item_data.get('work_package_id')}"
        }
        response["workPackageId"] = agenda_item_data.get("work_package_id")

    return response


    # Work-package-specific formatting removed to keep this module generic.
    # Controllers are responsible for assembling module-specific HAL responses.


def format_comment_response(
    comment_data: Dict[str, Any],
    base_url: str = "/api/v3",
) -> Dict[str, Any]:
    """HAL+JSON shape for a single comment (doc 35: unified send-event).

    Each comment row carries body + an inline attachments array of
    ``{url, filename, mimeType, sizeBytes, uploadedAt}``. Clients fetch
    file bytes from the URL directly — there is no per-attachment id
    or BE-streaming download link.

    A row may have:
      - body present, attachments empty   ⇒ comment-only
      - body NULL,    attachments present ⇒ file-only ("attachment-only" send)
      - body present, attachments present ⇒ comment with files (the
                                            email-shaped happy path)
    """
    cid = comment_data.get("id")
    target_kind = comment_data.get("target_kind")
    target_id = comment_data.get("target_id")
    author = comment_data.get("author") or {}
    attachments = comment_data.get("attachments") or []

    return {
        "_type": "Comment",
        "_links": {
            "self": {"href": f"{base_url}/comments/{cid}"},
            "target": {
                "href": f"{base_url}/{target_kind}s/{target_id}",
                "title": target_kind,
            },
        },
        "id": cid,
        "targetKind": target_kind,
        "targetId": target_id,
        "body": comment_data.get("body"),
        "author": {
            "id": author.get("id"),
            "login": author.get("login"),
            "firstName": author.get("first_name"),
            "lastName": author.get("last_name"),
            "email": author.get("email"),
        },
        "createdAt": comment_data.get("created_at"),
        "updatedAt": comment_data.get("updated_at"),
        "deletedAt": comment_data.get("deleted_at"),
        # Doc 35: each entry is already in wire shape (camelCase keys)
        # because the domain layer's ``AttachmentInfo.to_dict`` produces
        # exactly that. Pass through as-is.
        "attachments": list(attachments),
    }


def format_attachment_response(
    comment_data: Dict[str, Any],
    base_url: str = "/api/v3",
) -> Dict[str, Any]:
    """HAL+JSON shape for an "attachment" (doc 35: actually a comment row).

    Pre-doc-34 this formatted a row from the ``attachments`` table.
    After doc 35 there's no such table — every attachment lives on a
    comment row. This formatter is kept under its old name so the
    POST/GET/DELETE endpoints under ``/<entity>/{id}/attachments`` keep
    returning a recognisably-shaped payload for the FE.

    Strategy: emit the comment row in the comment shape, with the body
    typically NULL (file-only path). The FE iterates ``attachments``
    on the row to render files, exactly like comment rows.
    """
    return format_comment_response(comment_data, base_url)


def format_error_response(
    error_type: str,
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Format an error response in HAL+JSON format.

    Args:
        error_type: Type of error
        message: Error message
        details: Optional additional error details

    Returns:
        HAL+JSON formatted error response
    """
    response = {
        "_type": "Error",
        "errorIdentifier": error_type,
        "message": message
    }

    if details:
        response["_embedded"] = {"details": details}

    return response


def format_success_response(message: str) -> Dict[str, Any]:
    """
    Format a success response.

    Args:
        message: Success message

    Returns:
        HAL+JSON formatted success response
    """
    return {
        "_type": "Success",
        "message": message
    }

def api_response(
    *,
    data: Optional[Any] = None,
    message: Optional[Any] = None,
    error: Optional[Any] = None,
    status: int = 200,
) -> JSONResponse:
    """
    Generic API response envelope.
    Safe to use across all services.
    Does NOT affect HAL+JSON formatting.
    """

    payload = {
        "data": data,
        "message": message,
        "error": error,
        "status": status,
    }

    return JSONResponse(
        status_code=status,
        content=payload
    )