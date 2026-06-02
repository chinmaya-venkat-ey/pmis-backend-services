"""Unit tests for the Doc-41 RoleAssignmentCreateRequest validator.

Confirms scope exclusivity: at most one of
  - organization_id
  - project_id
  - project_ids (non-empty batch)
may be set in a single request.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.role_assignment import RoleAssignmentCreateRequest


def test_global_scope_passes():
    """All scope fields empty → global grant."""
    req = RoleAssignmentCreateRequest(role_id=1)
    assert req.organization_id is None
    assert req.project_id is None
    assert req.project_ids == []


def test_org_scope_passes():
    req = RoleAssignmentCreateRequest(role_id=1, organization_id="vend-A")
    assert req.organization_id == "vend-A"


def test_project_scope_passes():
    req = RoleAssignmentCreateRequest(role_id=1, project_id="proj-uuid")
    assert req.project_id == "proj-uuid"


def test_batch_project_scope_passes():
    req = RoleAssignmentCreateRequest(role_id=1, project_ids=["p1", "p2"])
    assert req.project_ids == ["p1", "p2"]


def test_org_plus_project_rejected():
    with pytest.raises(ValidationError) as exc:
        RoleAssignmentCreateRequest(
            role_id=1, organization_id="v-A", project_id="p-1",
        )
    assert "Exactly one" in str(exc.value)


def test_project_id_plus_batch_rejected():
    with pytest.raises(ValidationError):
        RoleAssignmentCreateRequest(
            role_id=1, project_id="p-1", project_ids=["p-2"],
        )


def test_org_plus_batch_rejected():
    with pytest.raises(ValidationError):
        RoleAssignmentCreateRequest(
            role_id=1, organization_id="v-A", project_ids=["p-1"],
        )
