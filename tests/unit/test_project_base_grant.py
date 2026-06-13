"""Unit tests for RbacRepository._project_base_reads — the curated cross-cutting
reads surfaced at GLOBAL scope for a project_admin/project_member (so a holder
with no project still has them). Keyed on the org_role column. No DB (mocks)."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.core.permissions import PROJECT_ROLE_BASE_CODES
from app.repositories.rbac_repository import RbacRepository


def _repo(org_role_column):
    repo = RbacRepository(MagicMock(name="session"))
    # self.db.execute(select(User.org_role)...).scalar() -> the column value
    repo.db.execute.return_value.scalar.return_value = org_role_column
    return repo


def test_project_admin_column_gets_curated_reads():
    repo = _repo("project_admin")
    reads = repo._project_base_reads("u-1")
    assert reads == set(PROJECT_ROLE_BASE_CODES)
    assert "users:read" in reads


def test_project_member_column_gets_curated_reads():
    assert _repo("project_member")._project_base_reads("u-2") == set(PROJECT_ROLE_BASE_CODES)


def test_column_normalized_case_and_whitespace():
    assert _repo("  Project_Admin  ")._project_base_reads("u-3") == set(PROJECT_ROLE_BASE_CODES)


def test_non_project_column_gets_nothing():
    for col in ("org_admin", "admin", "super_admin", "division_member", None, ""):
        assert _repo(col)._project_base_reads("u-4") == set(), col


def test_orgrole_fallback_synthesizes_entry_for_no_project_project_role():
    # No-project project_admin: column set, no assignment rows -> synthetic entry
    # so the user-facing orgRole still reflects the role.
    e = RbacRepository._column_role_fallback_entry("project_admin", [], {"project_admin": 4})
    assert e is not None
    assert e["role_name"] == "project_admin" and e["role_id"] == 4
    assert e["scope"] == "global"
    assert e["project_id"] is None and e["assignment_id"] is None

    # case/whitespace normalized
    assert RbacRepository._column_role_fallback_entry("  Project_Member ", [], {"project_member": 5})["role_name"] == "project_member"


def test_orgrole_fallback_skips_when_role_already_present():
    # A holder WITH projects already has project-scoped entries -> no duplicate.
    existing = [{"role_name": "project_admin", "scope": "project", "project_id": "p1"}]
    assert RbacRepository._column_role_fallback_entry("project_admin", existing, {"project_admin": 4}) is None


def test_orgrole_fallback_none_for_non_project_or_missing_role():
    for col in ("org_admin", "admin", "super_admin", "division_member", None, ""):
        assert RbacRepository._column_role_fallback_entry(col, [], {"project_admin": 4, "project_member": 5}) is None
    # column is a project role but the role id map lacks it (role missing)
    assert RbacRepository._column_role_fallback_entry("project_admin", [], {}) is None


def test_curated_set_excludes_project_nature_and_broad_reads():
    # Safety contract: nothing that could leak project access or broad user read.
    proj_domains = {
        "projects", "milestones", "activities", "tasks", "subtasks",
        "comments", "attachments", "project_members",
    }
    for code in PROJECT_ROLE_BASE_CODES:
        assert code.endswith(":read"), code
        assert code.split(":")[0] not in proj_domains, code
    assert "users:read_all" not in PROJECT_ROLE_BASE_CODES
    assert "users:list_all_orgs" not in PROJECT_ROLE_BASE_CODES
