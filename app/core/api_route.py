"""HalApiRoute — custom APIRoute that auto-wraps successful responses in
the canonical PMIS envelope with HAL+JSON inner shapes.

How it works:
  - Handlers / controllers stay unchanged. Pydantic ``response_model``
    still validates + serializes on the way out (including the IST
    coercion on ``app.schemas._base.ResponseModel``).
  - This route class intercepts the resulting ``JSONResponse``, decodes
    the body, wraps it via ``hal_resource`` / ``hal_collection``, and
    re-emits via ``api_response``.
  - ``StreamingResponse`` (file downloads) and non-JSON ``Response``
    returns pass through untouched.
  - Health / readiness routes are excluded at registration time (see
    ``install_hal_route_class`` below), so orchestrators see the raw
    ``{"status": "ok"}`` shape they expect.

``_type`` resolution: derived from the route's ``response_model`` class
name (``ProjectResponse`` → ``"Project"``). A schema can override with
``_hal_type: ClassVar[str] = "X"``.

Duplicated across all 4 services — keep in sync.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute, request_response

from app.core.response import api_response, hal_collection, hal_resource


_ENVELOPE_KEYS = frozenset({"data", "message", "error", "status"})

# Header names that JSONResponse will recompute from the new body — must
# not be carried over when we re-emit, or we'll send a wrong Content-Length.
_STALE_HEADERS = frozenset({"content-length", "content-type"})

# Keys that must NOT be camelCased. Standard HAL machinery uses leading-
# underscore conventions; the envelope-level keys ride on top.
_KEEP_KEYS = frozenset({
    "_type", "_links", "_embedded",
    "data", "message", "error", "status",
})


def _to_camel(name: str) -> str:
    """Convert ``snake_case_field`` → ``snakeCaseField``.

    Idempotent on already-camelCase / single-word strings. Preserves
    leading underscores (``_type`` → ``_type``).
    """
    if "_" not in name:
        return name
    # Preserve leading underscore (HAL convention).
    leading = ""
    body = name
    while body.startswith("_"):
        leading += "_"
        body = body[1:]
    if not body:
        return name
    parts = body.split("_")
    head = parts[0]
    tail = "".join(p.title() for p in parts[1:])
    return f"{leading}{head}{tail}"


def _camelize(value: Any) -> Any:
    """Recursively rewrite dict keys snake_case → camelCase.

    Keys in ``_KEEP_KEYS`` are preserved verbatim. The transformation is
    idempotent for keys that are already camelCase (no ``_`` in them).

    Conditional-field rules (monolith parity):
      * ``attachments`` is OMITTED from the wire when ``None`` — monolith
        only includes it on the GET single-project response, not on
        create/patch/upsert/lifecycle/list.
      * ``subtasks`` is OMITTED when ``None`` — monolith only includes
        the nested-tree field on the LIST endpoint
        (``GET /tasks/{id}/subtasks``); single-subtask GET / PATCH /
        DELETE / RESTORE return the flat shape without the field.

    Other ``None`` fields pass through unchanged (we don't strip None
    globally because description/category/etc. are legitimately ``null``
    on the wire).
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            # ``comment`` is the inline first-comment surfaced on the
            # multipart arm of M/A/T/S /create — JSON-arm and all
            # subsequent reads send ``None`` and the key is omitted from
            # the wire to match monolith's flat shape.
            if k in ("attachments", "subtasks", "comment") and v is None:
                continue
            new_key = k if k in _KEEP_KEYS else _to_camel(k)
            out[new_key] = _camelize(v)
        return out
    if isinstance(value, list):
        return [_camelize(v) for v in value]
    return value


def _is_json_response(response: Response) -> bool:
    """True iff ``response`` carries a JSON body.

    Covers two FastAPI 0.135+ shapes:
      * ``JSONResponse`` (when the route declares a custom ``response_class``
        or returns a JSONResponse directly).
      * ``Response(media_type="application/json")`` — FastAPI's "fast path"
        for Pydantic ``response_model`` returns, which skips constructing
        a JSONResponse and produces a bare Response with JSON bytes via
        Pydantic's Rust core (see fastapi/routing.py around the
        ``dump_json`` branch).
    """
    if isinstance(response, JSONResponse):
        return True
    media = getattr(response, "media_type", None) or ""
    return media.split(";", 1)[0].strip().lower() == "application/json"


def _hal_type_for(response_model: Optional[type]) -> str:
    """Derive the HAL ``_type`` from a Pydantic response model class.

    ``ProjectResponse`` → ``"Project"``. Override on the schema with
    ``_hal_type: ClassVar[str] = "X"`` if a custom name is needed.
    """
    if response_model is None:
        return "Resource"
    explicit = getattr(response_model, "_hal_type", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    name = getattr(response_model, "__name__", "")
    if name.endswith("Response"):
        return name[: -len("Response")] or "Resource"
    return name or "Resource"


def _looks_like_paged_dict(value: Any) -> bool:
    """The ``{items, total, offset, page_size}`` shape returned by a few
    list endpoints (project list, milestone list, etc.)."""
    return (
        isinstance(value, dict)
        and "items" in value
        and "total" in value
    )


# Plural collection name -> singular HAL ``_type``. Covers every entity
# this microservice exposes; matches the monolith's per-element wrapper
# (``_type: "Project"`` / ``"Milestone"`` / ``"Activity"`` / ``"Task"`` /
# ``"Subtask"`` / ``"Comment"``).
_ELEMENT_TYPE_BY_COLLECTION = {
    "projects": "Project",
    "milestones": "Milestone",
    "activities": "Activity",
    "tasks": "Task",
    "subtasks": "Subtask",
    "comments": "Comment",
    "audit-logs": "AuditLog",
}


def _collection_prefix_from_path(path: str) -> Optional[str]:
    """Derive the resource-collection base URL for the LAST entity in the
    request path — used as the prefix for resource self-links.

    ``/project/projects/create``               -> ``/project/projects``
    ``/project/projects/{id}``                 -> ``/project/projects``
    ``/project/projects/{id}/save``            -> ``/project/projects``
    ``/project/milestones/{id}/publish``       -> ``/project/milestones``
    ``/project/projects/{pid}/milestones``     -> ``/project/milestones``
                                                  (nested: last entity wins)
    ``/project/milestones/{mid}/comments``     -> ``/project/comments``
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return None
    for seg in reversed(parts):
        if seg in _ELEMENT_TYPE_BY_COLLECTION:
            return f"/{parts[0]}/{seg}"
    return "/" + "/".join(parts[:2])


def _element_type_for_path(path: str) -> str:
    """Find the singular HAL ``_type`` to stamp on each list element by
    walking BACK through the URL segments and picking the last entity
    collection name. Handles nested-list URLs like
    ``/project/projects/{pid}/milestones`` (element_type = Milestone)."""
    parts = [p for p in path.split("/") if p]
    for seg in reversed(parts):
        if seg in _ELEMENT_TYPE_BY_COLLECTION:
            return _ELEMENT_TYPE_BY_COLLECTION[seg]
    return "Resource"


def _wrap_element(
    item: dict, element_type: str, prefix: Optional[str],
) -> dict:
    """Stamp ``_type`` + ``_links.self`` on a single collection element.

    Matches monolith parity — every element in ``_embedded.elements`` is
    itself a full HAL resource (e.g. ``format_project_response`` builds
    each row this way before the controller bundles the list).

    For Milestone / Activity / Task / Subtask elements, also adds a
    ``_links.project`` back-link to the parent project (monolith parity).
    """
    camel = _camelize(item)
    rid = camel.get("id")
    title = camel.get("name")
    links: dict[str, dict] = {}
    if prefix and rid:
        self_link = {"href": f"{prefix}/{rid}"}
        if title:
            self_link["title"] = title
        links["self"] = self_link
    # Monolith parity: per-entity back-link to its direct parent in the
    # M → A → T → S chain (NOT a uniform "milestone" link).
    #   Activity → milestone, Task → activity, Subtask → task.
    if element_type == "Activity":
        milestone_id = camel.get("milestoneId") or item.get("milestone_id")
        if milestone_id:
            links["milestone"] = {"href": f"/project/milestones/{milestone_id}"}
    elif element_type == "Task":
        activity_id = camel.get("activityId") or item.get("activity_id")
        if activity_id:
            links["activity"] = {"href": f"/project/activities/{activity_id}"}
    elif element_type == "Subtask":
        task_id = camel.get("taskId") or item.get("task_id")
        if task_id:
            links["task"] = {"href": f"/project/tasks/{task_id}"}
    elif element_type == "Comment":
        # Monolith parity: comments add a ``_links.target`` pointing back
        # at the entity they were posted on. NOTE the monolith quirk:
        # the URL pluralisation is ``target_kind + "s"``, which yields
        # ``activitys`` (sic) for activity targets — we mirror it
        # byte-for-byte so the wire matches.
        target_kind = camel.get("targetKind") or item.get("target_kind")
        target_id = camel.get("targetId") or item.get("target_id")
        if target_kind and target_id:
            links["target"] = {
                "href": f"/project/{target_kind}s/{target_id}",
                "title": target_kind,
            }
    if element_type in ("Milestone", "Activity", "Task", "Subtask"):
        project_id = camel.get("projectId") or item.get("project_id")
        if project_id:
            links["project"] = {"href": f"/project/projects/{project_id}"}
    # Subtask-only: nested children inside the recursive ``subtasks`` tree
    # need the same ``_type`` + ``_links`` envelope as the top-level
    # element (monolith parity — every node in the tree is a full HAL
    # resource). Reuse this wrapper on each child so the structure walks
    # to any nesting depth.
    if element_type == "Subtask":
        nested = camel.get("subtasks")
        if isinstance(nested, list) and nested:
            camel["subtasks"] = [
                _wrap_element(child, element_type, prefix) for child in nested
            ]
    return {
        "_type": element_type,
        "_links": links,
        **camel,
    }


def _wrap_inline_comment(camel: dict) -> dict:
    """Promote an already-camelized comment dict to a full HAL Comment
    resource (``_type`` + ``_links: {self, target}``).

    Used by the M/A/T/S multipart-create response path to mirror the
    monolith's inline ``comment`` shape. The ``_links.target.href`` uses
    ``target_kind + "s"`` pluralisation — same monolith quirk that yields
    ``activitys`` for activity targets (matched byte-for-byte).
    """
    cid = camel.get("id")
    links: dict[str, dict] = {}
    if cid:
        links["self"] = {"href": f"/project/comments/{cid}"}
    target_kind = camel.get("targetKind")
    target_id = camel.get("targetId")
    if target_kind and target_id:
        links["target"] = {
            "href": f"/project/{target_kind}s/{target_id}",
            "title": target_kind,
        }
    out: dict[str, Any] = {"_type": "Comment"}
    if links:
        out["_links"] = links
    out.update(camel)
    return out


def _wrap(value: Any, hal_type: str, request_path: Optional[str] = None) -> Optional[dict]:
    """Convert a Pydantic-serialized body into the appropriate HAL inner
    shape. Returns the value to put under ``data``.

    Recursive snake_case → camelCase conversion is applied INSIDE this
    function so every wire-facing key matches the monolith's contract
    (``projectCode``, ``startDate``, ``ownerOther`` etc.).

    When ``request_path`` is provided and the wrapped resource carries an
    ``id``, ``_links.self.href`` is populated as
    ``{collection_prefix}/{id}`` and ``_links.self.title`` from the row's
    ``name`` — matches the monolith's ``format_project_response`` /
    ``format_*_response`` HAL self-link shape. Collection responses get
    auto-generated ``self`` / ``next`` / ``last`` pagination links built
    from the request path + ``offset`` / ``pageSize``.
    """
    if value is None:
        return None

    if _looks_like_paged_dict(value):
        # Element prefix uses the LAST entity name in path so id-scoped
        # element self-links resolve correctly even on nested list URLs
        # (e.g. /project/projects/{pid}/milestones -> element prefix is
        # /project/milestones, NOT /project/projects).
        element_prefix = _collection_prefix_from_path(request_path or "")
        element_type = _element_type_for_path(request_path or "")
        # Collection self/next/last use the FULL request URL path
        # (without query string) — preserves nested path like
        # /project/projects/{pid}/milestones. Monolith parity:
        # COMMENT collections do NOT carry a top-level ``_links`` block,
        # so we suppress base_path for them (hal_collection skips link
        # synthesis when base_path is None).
        collection_base = (request_path or "").split("?", 1)[0] or None
        if element_type == "Comment":
            collection_base = None
        items = value["items"] or []
        wrapped_elements = [
            _wrap_element(item, element_type, element_prefix) for item in items
        ]
        return hal_collection(
            wrapped_elements,
            total=int(value["total"]),
            offset=int(value.get("offset", 1)),
            page_size=int(value.get("page_size", len(items))),
            base_path=collection_base,
        )

    if isinstance(value, list):
        element_prefix = _collection_prefix_from_path(request_path or "")
        element_type = _element_type_for_path(request_path or "")
        collection_base = (request_path or "").split("?", 1)[0] or None
        wrapped_elements = [
            _wrap_element(v, element_type, element_prefix) if isinstance(v, dict)
            else _camelize(v)
            for v in value
        ]
        return hal_collection(
            wrapped_elements,
            total=len(value),
            offset=1,
            page_size=len(value),
            base_path=collection_base,
        )

    if isinstance(value, dict):
        # If the handler already produced an envelope, surface as-is.
        if _ENVELOPE_KEYS <= set(value.keys()):
            return value
        # Bare-data opt-out: certain monolith endpoints
        # (``/role-assignments``, ``/assignable-users``) return the bare
        # data dict directly under ``data`` with NO ``_type`` or
        # ``_links`` envelope. Service layer signals this with
        # ``_bare: True`` in the returned dict; we strip the marker and
        # return just the camelized payload.
        if value.pop("_bare", False):
            return _camelize(value)
        camel = _camelize(value)
        self_link = None
        extra_links = None
        if request_path:
            rid = camel.get("id")
            prefix = _collection_prefix_from_path(request_path)
            if rid and prefix:
                self_link = f"{prefix}/{rid}"
                title = camel.get("name")
                if title:
                    extra_links = {"self": {"href": self_link, "title": title}}
                    self_link = None  # consumed by extra_links override
        # Monolith parity: milestone / activity / task / subtask resources
        # carry a ``_links.project`` back-link, and each non-milestone
        # entity additionally carries a back-link to its DIRECT parent
        # in the M → A → T → S chain (NOT a uniform "milestone" link):
        #   Activity → milestone, Task → activity, Subtask → task.
        if hal_type in ("Milestone", "Activity", "Task", "Subtask"):
            project_id = camel.get("projectId") or value.get("project_id")
            if project_id:
                if extra_links is None:
                    extra_links = {}
                extra_links["project"] = {"href": f"/project/projects/{project_id}"}
        # Direct-parent back-link, inserted BEFORE the project link in
        # the rendered _links order (monolith parity — parent first,
        # then project).
        parent_key: Optional[str] = None
        parent_href: Optional[str] = None
        if hal_type == "Activity":
            milestone_id = camel.get("milestoneId") or value.get("milestone_id")
            if milestone_id:
                parent_key, parent_href = (
                    "milestone", f"/project/milestones/{milestone_id}",
                )
        elif hal_type == "Task":
            activity_id = camel.get("activityId") or value.get("activity_id")
            if activity_id:
                parent_key, parent_href = (
                    "activity", f"/project/activities/{activity_id}",
                )
        elif hal_type == "Subtask":
            task_id = camel.get("taskId") or value.get("task_id")
            if task_id:
                parent_key, parent_href = (
                    "task", f"/project/tasks/{task_id}",
                )
        elif hal_type == "Comment":
            # Monolith parity: a Comment's ``_links.self.href`` ALWAYS
            # points at ``/project/comments/{id}`` regardless of which
            # collection URL produced the response. The path-derived
            # prefix (e.g. ``/project/milestones`` for the M/A/T/S
            # attachment upload route) would yield the wrong self link
            # since the resource lives under ``/comments/{id}`` even
            # when reached via ``/milestones/{id}/attachments``.
            rid = camel.get("id")
            target_kind = camel.get("targetKind") or value.get("target_kind")
            target_id = camel.get("targetId") or value.get("target_id")
            if rid:
                if extra_links is None:
                    extra_links = {}
                ordered: dict[str, dict] = {
                    "self": {"href": f"/project/comments/{rid}"},
                }
                if target_kind and target_id:
                    # Pluralisation quirk: ``target_kind + "s"`` matches
                    # monolith byte-for-byte even though it yields
                    # ``activitys`` (sic) for activities.
                    ordered["target"] = {
                        "href": f"/project/{target_kind}s/{target_id}",
                        "title": target_kind,
                    }
                extra_links = ordered
                self_link = None
        if parent_key:
            if extra_links is None:
                extra_links = {}
            ordered: dict[str, dict] = {}
            if self_link:
                ordered["self"] = {"href": self_link}
            elif extra_links.get("self"):
                ordered["self"] = extra_links["self"]
            ordered[parent_key] = {"href": parent_href}
            if "project" in extra_links:
                ordered["project"] = extra_links["project"]
            extra_links = ordered
            # self_link already consumed into extra_links via "self".
            self_link = None
        # Monolith parity: inline ``comment`` on a M/A/T/S multipart
        # /create response is itself a full HAL Comment resource
        # (``_type`` + ``_links: {self, target}``). Pydantic produces a
        # flat camelized dict; promote it here.
        if hal_type in ("Milestone", "Activity", "Task", "Subtask"):
            inline_comment = camel.get("comment")
            if isinstance(inline_comment, dict) and inline_comment.get("id"):
                camel["comment"] = _wrap_inline_comment(inline_comment)
        return hal_resource(
            hal_type, camel,
            self_link=self_link, extra_links=extra_links,
        )

    # Scalar / unexpected — wrap minimally so the envelope stays valid.
    return {"_type": hal_type, "value": value}


class HalApiRoute(APIRoute):
    """APIRoute that wraps successful responses in the PMIS envelope."""

    def get_route_handler(self) -> Callable:
        original_handler = super().get_route_handler()
        hal_type = _hal_type_for(self.response_model)

        async def custom_handler(request: Request) -> Response:
            response = await original_handler(request)

            # Pass through anything that isn't a JSON-shaped response:
            # file downloads, redirects, custom Response subclasses.
            if isinstance(response, StreamingResponse):
                return response
            if not _is_json_response(response):
                return response

            # Decode the body Pydantic + FastAPI just serialized. The
            # ResponseModel.model_validator has already coerced datetimes
            # to IST at this point.
            try:
                inner = json.loads(response.body.decode("utf-8"))
            except (ValueError, AttributeError):
                return response

            # If the handler explicitly built an envelope (rare — e.g. a
            # special-cased exception handler), don't double-wrap.
            if isinstance(inner, dict) and _ENVELOPE_KEYS <= set(inner.keys()):
                return response

            wrapped = _wrap(inner, hal_type, request_path=request.url.path)

            passthrough_headers = {
                k: v
                for k, v in response.headers.items()
                if k.lower() not in _STALE_HEADERS
            }

            return api_response(
                data=wrapped,
                status=response.status_code,
                headers=passthrough_headers or None,
            )

        return custom_handler


def install_hal_route_class(app, *, skip_paths: Optional[Iterable[str]] = None) -> None:
    """Swap every APIRoute on the app to HalApiRoute and re-bake handlers.

    Called from ``main.py`` AFTER all ``include_router`` calls. Routes
    in ``skip_paths`` (typically ``/health`` and ``/ready``) keep their
    original APIRoute behaviour so orchestration probes see plain JSON.

    Safe because HalApiRoute adds no instance attributes — only a method
    override — so ``__class__`` reassignment is a no-op on state.
    """
    skip = set(skip_paths or ())
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if isinstance(route, HalApiRoute):
            continue
        if route.path in skip:
            continue
        route.__class__ = HalApiRoute
        # Re-bake the ASGI entry point so the new get_route_handler wins.
        route.app = request_response(route.get_route_handler())
