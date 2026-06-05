"""Schemas for the authorization decision surface (`/api/v3/authz/*`).

user-svc is the single Policy Decision Point. `/authz/context` returns the
fully-resolved authorization facts for the caller's token so that consuming
services stop re-deriving them from `users.*` themselves.

Scope-key encoding (the `scoped` map): the resolver returns
``Dict[(kind, id), Set[str]]``. On the wire that becomes a flat
``{"kind:id": [codes]}`` object, with the global tier encoded as the bare
key ``"global"`` (no id). Consumers decode by splitting on the first ``:``;
a key with no ``:`` means ``(kind, None)``.

Deliberately NO ``is_admin`` / ``is_super_admin``: admin-ness is just a set
of capability codes (the A1 audit removed the admin short-circuit), so the
context exposes codes only and lets the consumer's gates decide.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import Field

from app.schemas._base import ResponseModel


class AuthzContextResponse(ResponseModel):
    """The decided authorization context for one authenticated caller."""

    user_id: str = Field(description="The caller's user id (UUID).")
    vendor_id: Optional[str] = Field(
        default=None,
        description="The caller's own owning vendor/organization id, for "
        "row-level vendor scoping. NULL if the user has no vendor.",
    )
    permissions: List[str] = Field(
        default_factory=list,
        description="GLOBAL flat permission-code set (codes a "
        "`require_permission` gate consults). Project/org-scoped codes are "
        "NOT flattened in here — they live under `scoped`.",
    )
    scoped: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Per-scope permission codes keyed by `kind:id` "
        "(e.g. `project:<uuid>`, `org:<vendor_id>`), with the global tier "
        "under the bare key `global`. The vendor->project projection is "
        "already applied.",
    )


class AuthzUserSummary(ResponseModel):
    """One user returned by the `/authz/users` discovery query, with the
    distinct role names they hold (any tier/scope) so the caller can
    project a display role without re-reading users.* itself."""

    id: str
    login: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    vendor_id: Optional[str] = None
    division: Optional[str] = None
    roles: List[str] = Field(
        default_factory=list,
        description="Distinct role names the user holds, across the legacy "
        "and scoped tiers.",
    )
