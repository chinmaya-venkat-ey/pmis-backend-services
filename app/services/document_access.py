"""#323 — role-based document access: enforcement + management.

A "document" is an attachment row on ``project.comments`` (``body IS NULL``).
Whitelist semantics: a document with NO live ``DocumentAccessRule`` is PUBLIC;
one or more live rules make it RESTRICTED — visible/downloadable only to
superadmin/admin, the uploader, and users who match a rule (they hold the
rule's ``role_name`` at its project / org / division scope).

Enforcement runs at the attachment/comment LIST choke points (the only place a
document's URL is handed out — see ``app/services/attachment_service.py`` and
``app/services/discussion_feed_service.py``). Rule → eligible-user resolution
reuses user-management's ``/api/v3/authz/users`` discovery API via
``UserMgmtClient.fetch_users`` (same predicate the Manage-Team candidate
pickers use), cached per resolver so a document list makes at most one lookup
per distinct rule.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.models.document_access_rule import DocumentAccessRule
from app.repositories.document_access_rule_repository import (
    DocumentAccessRuleRepository,
)
from app.services.user_mgmt_client import UserMgmtClient


# A rule's resolution key — role + the single scope it resolves against.
_RuleKey = Tuple[str, Optional[str], Optional[str], Optional[str]]


class DocumentAccessContext:
    """The caller facts enforcement needs.

    ``authorization`` is the caller's raw ``Authorization`` header — forwarded
    verbatim to user-management (never a service token), matching the rest of
    this service's cross-service calls.
    """

    __slots__ = ("caller_user_id", "caller_is_admin", "authorization")

    def __init__(
        self,
        *,
        caller_user_id: Optional[str],
        caller_is_admin: bool,
        authorization: Optional[str],
    ) -> None:
        self.caller_user_id = caller_user_id
        self.caller_is_admin = bool(caller_is_admin)
        self.authorization = authorization


# A user-lookup returns the set of eligible user ids for one rule. Injectable
# for tests; the default hits user-management.
UserLookup = Callable[[DocumentAccessRule, DocumentAccessContext], Set[str]]


def _default_user_lookup(
    rule: DocumentAccessRule, ctx: DocumentAccessContext,
) -> Set[str]:
    """Resolve a rule → eligible user ids via user-management /authz/users.

    Selector precedence mirrors the discovery contract (exactly one selector):
    division (∩ role ∩ org) → org (vendor + role) → project (+ role).
    """
    client = UserMgmtClient()
    auth = ctx.authorization or ""
    if rule.division:
        users = client.fetch_users(
            authorization=auth, divisions=[rule.division],
            role=rule.role_name, org_id=rule.organization_id,
        )
    elif rule.organization_id:
        users = client.fetch_users(
            authorization=auth, vendor_ids=[rule.organization_id],
            role=rule.role_name,
        )
    else:
        users = client.fetch_users(
            authorization=auth, project_id=rule.project_id, role=rule.role_name,
        )
    return {u.get("id") for u in users if u.get("id")}


class DocumentAccessResolver:
    """Decides which documents (comment rows) a caller may see.

    Construct once per request/listing so the eligible-user cache is shared
    across every document on the page.
    """

    def __init__(
        self,
        db: Session,
        ctx: DocumentAccessContext,
        *,
        user_lookup: Optional[UserLookup] = None,
    ) -> None:
        self.repo = DocumentAccessRuleRepository(db)
        self.ctx = ctx
        self._lookup = user_lookup or _default_user_lookup
        self._cache: Dict[_RuleKey, Set[str]] = {}

    def _eligible_ids(self, rule: DocumentAccessRule) -> Set[str]:
        key: _RuleKey = (
            rule.role_name, rule.project_id, rule.organization_id, rule.division,
        )
        if key not in self._cache:
            self._cache[key] = self._lookup(rule, self.ctx)
        return self._cache[key]

    def _caller_matches(self, rules: Sequence[DocumentAccessRule]) -> bool:
        uid = self.ctx.caller_user_id
        if not uid:
            return False
        return any(uid in self._eligible_ids(r) for r in rules)

    def filter_rows(self, rows: list) -> list:
        """Return the subset of comment rows the caller may see.

        A row is kept when it has no live rule (public), OR the caller is
        superadmin/admin, OR the caller uploaded it, OR the caller matches a
        rule. Rows without a document rule (e.g. body-only discussion comments)
        are always kept — only attachment documents ever carry rules.
        """
        if not rows:
            return rows
        rules_by_comment = self.repo.map_for_comments([r.id for r in rows])
        if not rules_by_comment:
            return rows  # nothing restricted → no per-row work, no lookups
        kept = []
        for row in rows:
            rules = rules_by_comment.get(row.id)
            if not rules:
                kept.append(row)
                continue
            if self.ctx.caller_is_admin or (
                self.ctx.caller_user_id
                and row.author_user_id == self.ctx.caller_user_id
            ):
                kept.append(row)
                continue
            if self._caller_matches(rules):
                kept.append(row)
        return kept


def build_resolver(
    db: Session,
    *,
    caller_user_id: Optional[str],
    caller_is_admin: bool,
    authorization: Optional[str],
    user_lookup: Optional[UserLookup] = None,
) -> DocumentAccessResolver:
    """Convenience constructor from raw caller facts."""
    ctx = DocumentAccessContext(
        caller_user_id=caller_user_id,
        caller_is_admin=caller_is_admin,
        authorization=authorization,
    )
    return DocumentAccessResolver(db, ctx, user_lookup=user_lookup)


def caller_facts_from_request(request) -> Dict[str, object]:
    """Extract ``{caller_user_id, caller_is_admin, authorization}`` from a
    request's hydrated state — the keyword args every document-access-aware
    controller method expects. admin-ness is the global ``projects:admin_override``
    capability (admin / super_admin)."""
    from app.core.permissions import PROJECTS_ADMIN_OVERRIDE
    perms = getattr(request.state, "user_permissions", None) or set()
    return {
        "caller_user_id": getattr(request.state, "user_id", None),
        "caller_is_admin": PROJECTS_ADMIN_OVERRIDE in perms,
        "authorization": request.headers.get("authorization"),
    }
