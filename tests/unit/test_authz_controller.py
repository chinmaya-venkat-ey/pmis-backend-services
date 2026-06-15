"""Unit tests for AuthzController — the new logic is the scope-key encoding
(context) and the selector/union shaping (discovery)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.controllers.authz_controller import AuthzController
from app.core.errors import ValidationError


def _user(uid, login, **kw):
    return SimpleNamespace(
        id=uid,
        login=login,
        email=kw.get("email"),
        full_name=kw.get("full_name"),
        vendor_id=kw.get("vendor_id"),
        division=kw.get("division"),
    )


def test_get_context_encodes_scope_keys_and_sorts_codes():
    rbac = MagicMock()
    rbac.effective_permissions_for_user.return_value = {"users:read", "projects:read"}
    rbac.effective_permissions_by_scope.return_value = {
        ("global", None): {"users:read"},
        ("project", "P1"): {"projects:close", "projects:read"},
        ("org", "V1"): {"users:read"},
    }

    ctrl = AuthzController(rbac)
    resp = ctrl.get_context(user_id="u1", vendor_id="V9")

    assert resp.user_id == "u1"
    assert resp.vendor_id == "V9"
    # Flat set is sorted.
    assert resp.permissions == ["projects:read", "users:read"]
    # ("global", None) encodes to the bare key "global"; id-bearing scopes
    # encode to "kind:id"; code lists are sorted.
    assert resp.scoped["global"] == ["users:read"]
    assert resp.scoped["project:P1"] == ["projects:close", "projects:read"]
    assert resp.scoped["org:V1"] == ["users:read"]
    # Resolver is consulted with the caller's id, no extra logic injected.
    rbac.effective_permissions_for_user.assert_called_once_with("u1")
    rbac.effective_permissions_by_scope.assert_called_once_with("u1")


def test_get_context_empty_for_user_with_no_grants():
    rbac = MagicMock()
    rbac.effective_permissions_for_user.return_value = set()
    rbac.effective_permissions_by_scope.return_value = {}

    resp = AuthzController(rbac).get_context(user_id="u2", vendor_id=None)

    assert resp.permissions == []
    assert resp.scoped == {}
    assert resp.vendor_id is None


# ---------------------------------------------------------------------------
# Discovery: list_users
# ---------------------------------------------------------------------------

def test_list_users_project_mode_attaches_roles_and_sorts():
    query = MagicMock()
    query.users_by_project_role.return_value = [_user("u2", "bob"), _user("u1", "alice")]
    query.roles_by_user_ids.return_value = {"u1": ["project_admin"], "u2": ["project_member"]}

    out = AuthzController(MagicMock(), query).list_users(project_id="P1")

    assert [u.login for u in out] == ["alice", "bob"]  # sorted by login
    assert out[0].roles == ["project_admin"]
    query.users_by_project_role.assert_called_once_with("P1", None)


def test_list_users_org_mode_excludes_admin_tier():
    query = MagicMock()
    query.users_by_org_role.return_value = [_user("u1", "alice"), _user("admin1", "zadmin")]
    query.admin_tier_user_ids.return_value = {"admin1"}
    query.roles_by_user_ids.return_value = {"u1": ["org_admin"]}

    out = AuthzController(MagicMock(), query).list_users(
        vendor_ids=["V1"], role="org_admin", exclude_admin_tier=True,
    )

    assert [u.id for u in out] == ["u1"]
    query.users_by_org_role.assert_called_once_with(["V1"], "org_admin")


def test_list_users_division_mode():
    query = MagicMock()
    query.users_by_division.return_value = [_user("u1", "alice", division="TMD2")]
    query.roles_by_user_ids.return_value = {}

    out = AuthzController(MagicMock(), query).list_users(divisions=["TMD2"])

    assert [u.id for u in out] == ["u1"]
    assert out[0].roles == []
    query.users_by_division.assert_called_once_with(["TMD2"])


def test_list_users_requires_exactly_one_selector():
    ctrl = AuthzController(MagicMock(), MagicMock())
    with pytest.raises(ValidationError):
        ctrl.list_users()  # zero selectors
    with pytest.raises(ValidationError):
        ctrl.list_users(project_id="P1", divisions=["D1"])  # two selectors


def test_list_assignable_users_delegates_and_sorts():
    query = MagicMock()
    query.users_assignable_to_project.return_value = [
        _user("u2", "bob"), _user("u1", "alice"),
    ]
    query.roles_by_user_ids.return_value = {
        "u1": ["project_admin"], "u2": ["org_admin"],
    }

    out = AuthzController(MagicMock(), query).list_assignable_users(
        project_id="P1", role="project_admin",
    )

    assert [u.login for u in out] == ["alice", "bob"]  # sorted by login
    query.users_assignable_to_project.assert_called_once_with("P1", "project_admin")


def test_list_assignable_users_rejects_bad_role():
    ctrl = AuthzController(MagicMock(), MagicMock())
    for bad in ("org_admin", "admin", "garbage", ""):
        with pytest.raises(ValidationError):
            ctrl.list_assignable_users(project_id="P1", role=bad)
