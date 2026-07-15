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

# Approval-state enum TOKENS that appear as object KEYS in the dashboard
# ``statusByItems`` map (e.g. ``{"pending_division": 6, ...}``). These are
# data codes, not field names — the same tokens are used as ``approvalState``
# VALUES on item rows (values are never camelized), so the keys must stay
# snake_case too to keep the contract self-consistent and match the FE spec.
# No other endpoint emits these as keys, so preserving them globally is safe.
_PRESERVE_KEYS = frozenset({
    "pending_division", "pending_owner", "division_approved",
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
            new_key = k if (k in _KEEP_KEYS or k in _PRESERVE_KEYS) else _to_camel(k)
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
    "cost-items": "CostItem",
    "payment-terms": "PaymentTerm",
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


def _element_self_link(prefix: Optional[str], rid: Any, title: Any) -> Optional[dict]:
    """Build ``{href, title?}`` for the element's self link, or None when
    no prefix/id is available."""
    if not (prefix and rid):
        return None
    self_link: dict[str, Any] = {"href": f"{prefix}/{rid}"}
    if title:
        self_link["title"] = title
    return self_link


def _element_direct_parent_link(
    element_type: str, camel: dict, item: dict,
) -> Optional[tuple[str, dict]]:
    """Per-entity direct-parent backlink (monolith parity — Activity →
    milestone, Task → activity, Subtask → task, Comment → target).
    Returns ``(link_key, link_obj)`` or None."""
    if element_type == "Activity":
        mid = camel.get("milestoneId") or item.get("milestone_id")
        if mid:
            return ("milestone", {"href": f"/project/milestones/{mid}"})
    elif element_type == "Task":
        aid = camel.get("activityId") or item.get("activity_id")
        if aid:
            return ("activity", {"href": f"/project/activities/{aid}"})
    elif element_type == "Subtask":
        tid = camel.get("taskId") or item.get("task_id")
        if tid:
            return ("task", {"href": f"/project/tasks/{tid}"})
    elif element_type == "Comment":
        # Pluralisation quirk: ``target_kind + "s"`` matches monolith
        # byte-for-byte even though it yields ``activitys`` (sic).
        target_kind = camel.get("targetKind") or item.get("target_kind")
        target_id = camel.get("targetId") or item.get("target_id")
        if target_kind and target_id:
            return (
                "target",
                {
                    "href": f"/project/{target_kind}s/{target_id}",
                    "title": target_kind,
                },
            )
    return None


def _element_project_link(
    element_type: str, camel: dict, item: dict,
) -> Optional[dict]:
    """``_links.project`` backlink for Milestone / Activity / Task /
    Subtask elements (monolith parity)."""
    if element_type not in ("Milestone", "Activity", "Task", "Subtask"):
        return None
    project_id = camel.get("projectId") or item.get("project_id")
    if not project_id:
        return None
    return {"href": f"/project/projects/{project_id}"}


def _recurse_into_subtask_children(
    element_type: str, camel: dict, prefix: Optional[str],
) -> None:
    """Subtask-only: each node in the recursive ``subtasks`` tree gets the
    same ``_type`` + ``_links`` envelope as the top-level element. Mutates
    ``camel`` in place."""
    if element_type != "Subtask":
        return
    nested = camel.get("subtasks")
    if isinstance(nested, list) and nested:
        camel["subtasks"] = [
            _wrap_element(child, element_type, prefix) for child in nested
        ]


def _wrap_element(
    item: dict, element_type: str, prefix: Optional[str],
) -> dict:
    """Stamp ``_type`` + ``_links.self`` on a single collection element.

    Matches monolith parity — every element in ``_embedded.elements`` is
    itself a full HAL resource (e.g. ``format_project_response`` builds
    each row this way before the controller bundles the list).

    For Milestone / Activity / Task / Subtask elements, also adds a
    ``_links.project`` back-link to the parent project (monolith parity).

    Link insertion order preserved (self → direct-parent → project), so
    the rendered ``_links`` block on the wire is byte-identical to the
    legacy in-line form.
    """
    camel = _camelize(item)
    links: dict[str, dict] = {}

    self_link = _element_self_link(prefix, camel.get("id"), camel.get("name"))
    if self_link is not None:
        links["self"] = self_link

    parent = _element_direct_parent_link(element_type, camel, item)
    if parent is not None:
        links[parent[0]] = parent[1]

    project_link = _element_project_link(element_type, camel, item)
    if project_link is not None:
        links["project"] = project_link

    _recurse_into_subtask_children(element_type, camel, prefix)

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


def _wrap_paged_dict(value: dict, request_path: Optional[str]) -> dict:
    """Wrap a paged dict (``{items, total, offset, page_size}``) into a
    HAL collection envelope. Comment collections suppress the top-level
    ``_links`` block (monolith parity)."""
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
        # page_size None => "return all" (no cap); hal_collection renders it as
        # a single full page. Don't int() it in that case.
        page_size=(None if value.get("page_size") is None else int(value["page_size"])),
        base_path=collection_base,
    )


def _wrap_bare_list(value: list, request_path: Optional[str]) -> dict:
    """Wrap a bare list (no pagination metadata) as a HAL collection. Each
    dict element is wrapped via ``_wrap_element``; scalars are camelized
    inline."""
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


def _resource_direct_parent(
    hal_type: str, camel: dict, value: dict,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve the (key, href) for the resource's direct-parent backlink
    in the M → A → T → S chain. Returns (None, None) for hal types that
    don't carry one (Milestone, Comment, Project, etc.)."""
    if hal_type == "Activity":
        mid = camel.get("milestoneId") or value.get("milestone_id")
        if mid:
            return ("milestone", f"/project/milestones/{mid}")
    elif hal_type == "Task":
        aid = camel.get("activityId") or value.get("activity_id")
        if aid:
            return ("activity", f"/project/activities/{aid}")
    elif hal_type == "Subtask":
        tid = camel.get("taskId") or value.get("task_id")
        if tid:
            return ("task", f"/project/tasks/{tid}")
    return (None, None)


def _build_comment_resource_links(camel: dict, value: dict) -> Optional[dict]:
    """Comment resources override the self-link to always point at
    ``/project/comments/{id}`` regardless of which collection URL produced
    the response. Returns the extra_links dict (self + optional target)
    or None when the comment has no id."""
    rid = camel.get("id")
    if not rid:
        return None
    ordered: dict[str, dict] = {
        "self": {"href": f"/project/comments/{rid}"},
    }
    target_kind = camel.get("targetKind") or value.get("target_kind")
    target_id = camel.get("targetId") or value.get("target_id")
    if target_kind and target_id:
        # Pluralisation quirk: ``target_kind + "s"`` matches monolith
        # byte-for-byte even though it yields ``activitys`` (sic) for
        # activities.
        ordered["target"] = {
            "href": f"/project/{target_kind}s/{target_id}",
            "title": target_kind,
        }
    return ordered


def _reorder_links_with_parent(
    self_link: Optional[str],
    extra_links: Optional[dict],
    parent_key: str,
    parent_href: str,
) -> dict:
    """Reorder extra_links so the rendered key order is self → direct-
    parent → project (monolith parity — parent first, then project)."""
    extra_links = extra_links or {}
    ordered: dict[str, dict] = {}
    if self_link:
        ordered["self"] = {"href": self_link}
    elif extra_links.get("self"):
        ordered["self"] = extra_links["self"]
    ordered[parent_key] = {"href": parent_href}
    if "project" in extra_links:
        ordered["project"] = extra_links["project"]
    return ordered


def _promote_inline_comment(hal_type: str, camel: dict) -> None:
    """Inline ``comment`` on a M/A/T/S multipart-create response is itself
    a full HAL Comment resource. Pydantic produces a flat camelized dict;
    promote it in place."""
    if hal_type not in ("Milestone", "Activity", "Task", "Subtask"):
        return
    inline_comment = camel.get("comment")
    if isinstance(inline_comment, dict) and inline_comment.get("id"):
        camel["comment"] = _wrap_inline_comment(inline_comment)


def _wrap_dict_resource(
    value: dict, hal_type: str, request_path: Optional[str],
) -> dict:
    """Wrap a single dict resource into the HAL envelope shape (``_type`` +
    ``_links: {self, [direct-parent,] [project]}``). Handles envelope-
    passthrough, ``_bare`` opt-out, Comment self-link override, and the
    M → A → T → S parent/project backlink ordering."""
    # If the handler already produced an envelope, surface as-is.
    if _ENVELOPE_KEYS <= set(value.keys()):
        return value
    # Bare-data opt-out: certain monolith endpoints
    # (``/role-assignments``, ``/assignable-users``) return the bare
    # data dict directly under ``data`` with NO ``_type`` or
    # ``_links`` envelope.
    if value.pop("_bare", False):
        return _camelize(value)

    camel = _camelize(value)
    self_link: Optional[str] = None
    extra_links: Optional[dict] = None

    if request_path:
        rid = camel.get("id")
        prefix = _collection_prefix_from_path(request_path)
        if rid and prefix:
            self_link = f"{prefix}/{rid}"
            title = camel.get("name")
            if title:
                extra_links = {"self": {"href": self_link, "title": title}}
                self_link = None  # consumed by extra_links override

    # Monolith parity: M / A / T / S resources carry a ``_links.project``
    # back-link (inserted AFTER the direct-parent link in the final order).
    if hal_type in ("Milestone", "Activity", "Task", "Subtask"):
        project_id = camel.get("projectId") or value.get("project_id")
        if project_id:
            extra_links = extra_links or {}
            extra_links["project"] = {"href": f"/project/projects/{project_id}"}

    # Direct-parent link, inserted BEFORE project in the rendered order.
    parent_key, parent_href = _resource_direct_parent(hal_type, camel, value)

    # Comment resources override the self-link path (always points at
    # /project/comments/{id} regardless of producing route).
    if hal_type == "Comment":
        comment_links = _build_comment_resource_links(camel, value)
        if comment_links is not None:
            extra_links = comment_links
            self_link = None

    if parent_key:
        extra_links = _reorder_links_with_parent(
            self_link, extra_links, parent_key, parent_href,
        )
        # self_link consumed into extra_links via "self".
        self_link = None

    _promote_inline_comment(hal_type, camel)

    return hal_resource(
        hal_type, camel,
        self_link=self_link, extra_links=extra_links,
    )


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

    Branch dispatch: None → None; paged dict → collection; bare list →
    collection; dict → resource (with envelope-passthrough + ``_bare``
    opt-out + Comment self-link override + M/A/T/S parent/project
    backlinks); anything else → scalar wrap. Branch order preserved so
    response shape matches the legacy in-line form byte-for-byte.
    """
    if value is None:
        return None
    if _looks_like_paged_dict(value):
        return _wrap_paged_dict(value, request_path)
    if isinstance(value, list):
        return _wrap_bare_list(value, request_path)
    if isinstance(value, dict):
        return _wrap_dict_resource(value, hal_type, request_path)
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
