"""#323 — document access resolver decision logic (unit).

Covers the whitelist rule: a document with no rule is public; a restricted
document is visible only to admins, the uploader, and callers who match a rule.
The user-lookup (user-management /authz/users) is injected so these tests make
no HTTP calls.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services.document_access import DocumentAccessContext, DocumentAccessResolver


def _row(comment_id, uploader):
    return SimpleNamespace(id=comment_id, author_user_id=uploader)


def _rule(role_name, project_id="P", organization_id=None, division=None):
    return SimpleNamespace(
        role_name=role_name, project_id=project_id,
        organization_id=organization_id, division=division,
    )


class _FakeRepo:
    """Stand-in for DocumentAccessRuleRepository.map_for_comments."""

    def __init__(self, rules_by_comment):
        self._rules = rules_by_comment

    def map_for_comments(self, comment_ids):
        return {c: self._rules[c] for c in comment_ids if c in self._rules}


def _resolver(ctx, rules_by_comment, eligible_by_role):
    def lookup(rule, _ctx):
        return set(eligible_by_role.get(rule.role_name, set()))

    r = DocumentAccessResolver.__new__(DocumentAccessResolver)
    r.repo = _FakeRepo(rules_by_comment)
    r.ctx = ctx
    r._lookup = lookup
    r._cache = {}
    return r


def _ctx(user_id, is_admin=False):
    return DocumentAccessContext(
        caller_user_id=user_id, caller_is_admin=is_admin, authorization="Bearer x",
    )


def test_public_document_visible_to_everyone():
    rows = [_row("doc1", "uploaderX")]
    res = _resolver(_ctx("stranger"), rules_by_comment={}, eligible_by_role={})
    assert [r.id for r in res.filter_rows(rows)] == ["doc1"]


def test_restricted_document_hidden_from_non_matching_user():
    rows = [_row("doc1", "uploaderX")]
    res = _resolver(
        _ctx("stranger"),
        rules_by_comment={"doc1": [_rule("division_approver")]},
        eligible_by_role={"division_approver": {"alice"}},
    )
    assert res.filter_rows(rows) == []


def test_restricted_document_visible_to_matching_role_holder():
    rows = [_row("doc1", "uploaderX")]
    res = _resolver(
        _ctx("alice"),
        rules_by_comment={"doc1": [_rule("division_approver")]},
        eligible_by_role={"division_approver": {"alice"}},
    )
    assert [r.id for r in res.filter_rows(rows)] == ["doc1"]


def test_restricted_document_always_visible_to_admin():
    rows = [_row("doc1", "uploaderX")]
    res = _resolver(
        _ctx("someadmin", is_admin=True),
        rules_by_comment={"doc1": [_rule("division_approver")]},
        eligible_by_role={"division_approver": {"alice"}},
    )
    assert [r.id for r in res.filter_rows(rows)] == ["doc1"]


def test_restricted_document_visible_to_uploader():
    rows = [_row("doc1", "uploaderX")]
    res = _resolver(
        _ctx("uploaderX"),
        rules_by_comment={"doc1": [_rule("division_approver")]},
        eligible_by_role={"division_approver": {"alice"}},
    )
    assert [r.id for r in res.filter_rows(rows)] == ["doc1"]


def test_anonymous_caller_sees_only_public():
    rows = [_row("pub", "up"), _row("secret", "up")]
    res = _resolver(
        _ctx(None),
        rules_by_comment={"secret": [_rule("project_member")]},
        eligible_by_role={"project_member": {"alice"}},
    )
    assert [r.id for r in res.filter_rows(rows)] == ["pub"]


def test_multiple_rules_any_match_grants_access():
    rows = [_row("doc1", "up")]
    res = _resolver(
        _ctx("bob"),
        rules_by_comment={"doc1": [_rule("division_approver"), _rule("project_member")]},
        eligible_by_role={"division_approver": {"alice"}, "project_member": {"bob"}},
    )
    assert [r.id for r in res.filter_rows(rows)] == ["doc1"]


def test_lookup_is_cached_per_rule_key():
    calls = {"n": 0}

    def lookup(rule, _ctx):
        calls["n"] += 1
        return {"alice"}

    ctx = _ctx("stranger")
    res = DocumentAccessResolver.__new__(DocumentAccessResolver)
    res.repo = _FakeRepo({
        "d1": [_rule("division_approver")],
        "d2": [_rule("division_approver")],
    })
    res.ctx = ctx
    res._lookup = lookup
    res._cache = {}
    res.filter_rows([_row("d1", "u"), _row("d2", "u")])
    # Same (role, project, org, division) key across both docs → one lookup.
    assert calls["n"] == 1
