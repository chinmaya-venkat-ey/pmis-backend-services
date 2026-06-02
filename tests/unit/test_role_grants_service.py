"""Unit tests for RoleGrantsService — the static Doc-42b grant matrix."""
from __future__ import annotations

from app.core.permissions import (
    ADMIN_ROLE,
    DIVISION_MEMBER_ROLE,
    ORG_ADMIN_ROLE,
    PROJECT_ADMIN_ROLE,
    PROJECT_MEMBER_ROLE,
    SUPER_ADMIN_ROLE,
)
from app.services.role_grants_service import RoleGrantsService


def test_super_admin_can_grant_super_admin():
    """Doc-42b: only super_admin holds SUPER_ADMIN-grant in the matrix."""
    matrix = RoleGrantsService().get_matrix_for(SUPER_ADMIN_ROLE)
    names = {g.name for g in matrix.grantable_roles}
    assert SUPER_ADMIN_ROLE in names


def test_admin_cannot_grant_super_admin():
    matrix = RoleGrantsService().get_matrix_for(ADMIN_ROLE)
    names = {g.name for g in matrix.grantable_roles}
    assert SUPER_ADMIN_ROLE not in names


def test_org_admin_can_grant_project_roles_only():
    matrix = RoleGrantsService().get_matrix_for(ORG_ADMIN_ROLE)
    names = {g.name for g in matrix.grantable_roles}
    assert names == {PROJECT_ADMIN_ROLE, PROJECT_MEMBER_ROLE, DIVISION_MEMBER_ROLE}


def test_project_admin_can_only_grant_project_member():
    matrix = RoleGrantsService().get_matrix_for(PROJECT_ADMIN_ROLE)
    names = {g.name for g in matrix.grantable_roles}
    assert names == {PROJECT_MEMBER_ROLE}


def test_project_member_grants_nothing():
    matrix = RoleGrantsService().get_matrix_for(PROJECT_MEMBER_ROLE)
    assert matrix.grantable_roles == []


def test_unknown_role_returns_empty():
    matrix = RoleGrantsService().get_matrix_for("totally-not-a-role")
    assert matrix.grantable_roles == []
    assert matrix.role_name == "totally-not-a-role"
