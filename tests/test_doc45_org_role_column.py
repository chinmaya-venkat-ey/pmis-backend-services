"""Doc 45 round 9b — `users.org_role` tier column.

Pre-fix: creating a user with ``orgRole=project_admin`` (or
``project_member`` / ``division_member``) and ``project_ids=[]``
silently dropped the orgRole intent because the create service
only writes a row in ``user_role_assignments`` when there's a
project_id to attach the role to. Subsequent ``GET /users/{id}``
called ``derive_org_role`` which read exclusively from
``user_role_assignments`` / ``user_roles`` → returned ``null``.

Round 9b: the create service now persists the orgRole on the user
row (``users.org_role``). ``derive_org_role`` falls back to that
column when no role-assignment row matches a known FE tier.
Authorization is unchanged — permissions still come from the
role-assignment tables.
"""
from uuid import uuid4

import pytest

from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.vendor import VendorModel


@pytest.fixture
def sample_vendor(db_session):
    v = VendorModel(
        id=str(uuid4()),
        name=f"Vendor-{uuid4().hex[:6]}",
        description="for tests",
        active=True,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


@pytest.fixture
def sample_project_for_user(db_session):
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"UIDAI-PR{uuid4().hex[:14].upper()}",
        name="Project for org-role tests",
        description="-",
        active=True, public=False, status="published",
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _create_via_api(client, headers, **overrides):
    body = {
        "login": "doc45_user",
        "email": "doc45_user@example.com",
        "password": "Pmis@1234",
        "firstName": "T",
        "lastName": "User",
        "phoneNumber": "+919999999999",
        "division": "tmd1",
        "vendorId": None,
        "project_ids": [],
        "orgRole": None,
    }
    body.update(overrides)
    return client.post("/api/v3/users/create", json=body, headers=headers)


class TestOrgRoleSurvivesEmptyProjectIds:
    """The original bug — create with project-tier orgRole + empty
    project_ids → response now carries the orgRole."""

    def test_project_admin_with_no_projects(
        self, client, admin_user, admin_headers, sample_vendor, db_session,
    ):
        resp = _create_via_api(
            client, admin_headers,
            login="r9b_pa", email="r9b_pa@example.com",
            vendorId=sample_vendor.id,
            project_ids=[],
            orgRole="project_admin",
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["orgRole"] == "project_admin", (
            f"orgRole label dropped — got {data['orgRole']}"
        )
        # Column persisted on the row.
        row = db_session.query(UserModel).filter_by(id=data["id"]).one()
        assert row.org_role == "project_admin"

    def test_project_member_with_no_projects(
        self, client, admin_user, admin_headers, sample_vendor,
    ):
        resp = _create_via_api(
            client, admin_headers,
            login="r9b_pm", email="r9b_pm@example.com",
            vendorId=sample_vendor.id,
            project_ids=[],
            orgRole="project_member",
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["orgRole"] == "project_member"

    def test_division_member_column_persisted_but_not_in_projection(
        self, client, admin_user, admin_headers, sample_vendor, db_session,
    ):
        """``division_member`` is intentionally NOT surfaced via
        ``orgRole`` (the FE's enum excludes it — see RbacRepository
        comment). The column is still persisted so future workbox
        flows can read it, but ``derive_org_role`` keeps returning
        None for division_member-only users."""
        resp = _create_via_api(
            client, admin_headers,
            login="r9b_dm", email="r9b_dm@example.com",
            vendorId=sample_vendor.id,
            project_ids=[],
            orgRole="division_member",
        )
        assert resp.status_code == 201, resp.text
        # Wire response: orgRole stays None per the FE-projection rule.
        assert resp.json()["data"]["orgRole"] is None
        # Column persisted regardless.
        row = db_session.query(UserModel).filter_by(
            id=resp.json()["data"]["id"]
        ).one()
        assert row.org_role == "division_member"


class TestOrgRoleSurvivesGetById:
    """Subsequent GET /users/{id} returns the column-backed orgRole
    when no role-assignment row exists."""

    def test_get_returns_orgrole_from_column(
        self, client, admin_user, admin_headers, sample_vendor,
    ):
        create = _create_via_api(
            client, admin_headers,
            login="r9b_get", email="r9b_get@example.com",
            vendorId=sample_vendor.id,
            project_ids=[],
            orgRole="project_admin",
        )
        uid = create.json()["data"]["id"]

        resp = client.get(f"/api/v3/users/{uid}", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["orgRole"] == "project_admin"


class TestRoleAssignmentRowStillWins:
    """When the user has BOTH a column value AND a role-assignment row,
    the assignment-row tier wins (it's the source of truth for
    permissions). The column is a fallback only."""

    def test_assignment_row_overrides_column(
        self, client, admin_user, admin_headers, sample_vendor,
        sample_project_for_user, db_session,
    ):
        # Create with orgRole=project_admin AND a project — this should
        # write both the column AND a role-assignment row.
        create = _create_via_api(
            client, admin_headers,
            login="r9b_both", email="r9b_both@example.com",
            vendorId=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
            orgRole="project_admin",
        )
        assert create.status_code == 201, create.text
        data = create.json()["data"]
        assert data["orgRole"] == "project_admin"

        # Column also set as a fallback.
        row = db_session.query(UserModel).filter_by(id=data["id"]).one()
        assert row.org_role == "project_admin"
