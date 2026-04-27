"""HAL+JSON response helpers — slimmed to user-service needs.

Monolith has formatters for many entities (projects, meetings, etc.);
this service only deals with users, so only user-related helpers are
included. Keeps the same wire format as the monolith.
"""
from typing import Any, Dict, List, Optional

from fastapi.responses import JSONResponse


def format_user_response(
    user_data: Dict[str, Any],
    base_url: str = "/api/v3",
) -> Dict[str, Any]:
    """HAL+JSON shape for a single user — identical to monolith."""
    user_id = user_data.get("id")
    return {
        "_type": "User",
        "_links": {
            "self": {
                "href": f"{base_url}/users/{user_id}",
                "title": user_data.get("login"),
            }
        },
        "id": user_id,
        "login": user_data.get("login"),
        "firstName": user_data.get("first_name"),
        "lastName": user_data.get("last_name"),
        "email": user_data.get("email"),
        "admin": user_data.get("admin", False),
        "status": user_data.get("status", "active"),
        "createdAt": user_data.get("created_at"),
        "updatedAt": user_data.get("updated_at"),
    }


def format_collection_response(
    items: List[Dict[str, Any]],
    total: int,
    page: int,
    page_size: int,
    base_url: str = "/api/v3",
    collection_type: str = "users",
) -> Dict[str, Any]:
    """HAL+JSON collection envelope with pagination links."""
    if page_size is None or page_size <= 0:
        page_size = 20
    if page is None or page < 1:
        page = 1

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    links = {
        "self": {
            "href": f"{base_url}/{collection_type}?offset={page}&pageSize={page_size}",
        }
    }
    if page > 1:
        links["first"] = {
            "href": f"{base_url}/{collection_type}?offset=1&pageSize={page_size}",
        }
        links["prev"] = {
            "href": f"{base_url}/{collection_type}?offset={page - 1}&pageSize={page_size}",
        }
    if page < total_pages:
        links["next"] = {
            "href": f"{base_url}/{collection_type}?offset={page + 1}&pageSize={page_size}",
        }
        links["last"] = {
            "href": f"{base_url}/{collection_type}?offset={total_pages}&pageSize={page_size}",
        }

    if collection_type == "users":
        formatted_items = [format_user_response(item, base_url) for item in items]
    else:
        formatted_items = items

    return {
        "_type": "Collection",
        "_links": links,
        "total": total,
        "count": len(items),
        "pageSize": page_size,
        "offset": page,
        "_embedded": {"elements": formatted_items},
    }


def format_error_response(
    error_type: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resp = {
        "_type": "Error",
        "errorIdentifier": error_type,
        "message": message,
    }
    if details:
        resp["_embedded"] = {"details": details}
    return resp


def format_success_response(message: str) -> Dict[str, Any]:
    return {"_type": "Success", "message": message}


def api_response(
    *,
    data: Optional[Any] = None,
    message: Optional[Any] = None,
    error: Optional[Any] = None,
    status: int = 200,
) -> JSONResponse:
    """Generic envelope: {data, message, error, status}."""
    return JSONResponse(
        status_code=status,
        content={"data": data, "message": message, "error": error, "status": status},
    )
