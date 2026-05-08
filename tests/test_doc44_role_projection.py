"""Doc 44 — FE-friendly role projection.

Covers:
  * ``orgRole`` derivation (highest tier the user holds).
  * ``vendorId`` flat alias on user response.
  * ``projects[].role`` enrichment from doc-41 user_role_assignments.
  * Login + /me + introspect surfaces the projection.
  * /master/roles entries carry ``displayName``.
  * POST /users/create accepts ``orgRole`` + ``projectAssignments`` and
    writes the matching role-assignment rows in one transaction.
  * Caller-vs-target validation on create-with-orgRole (admin can't
    create super_admin, etc).
"""
from uuid import uuid4

import pytest

from app.core.security import create_access_token, hash_password
from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from app.infrastructure.db.models.vendor import VendorModel
from app.infrastructure.db.repositories.rbac_repository import RbacRepository


# ---------------------------------------------------------------------------
# Local helpers + fixtures
# ---------------------------------------------------------------------------

def _bootstrap_super_admin(db_session) -> tuple[UserModel, dict]:
    """Create a super_admin user via doc-41 user_role_assignments."""
    RbacRepository(db_session).sync_builtin_permissions()
    db_session.commit()
    sa_role_id = (
        db_session.query(RoleModel).filter(RoleModel.name == "super_admin")
        .one().id
    )
    user = UserModel(
        login=f"sa-{uuid4().hex[:6]}",
        email=f"sa-{uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Doc44Test!"),
        first_name="Super",
        last_name="Admin",
        status="active",
        two_factor_enabled=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    db_session.add(UserRoleAssignmentModel(
        user_id=user.id, role_id=sa_role_id,
    ))
    db_session.commit()
    return user, {
        "Authorization": f"Bearer " + create_access_token({
            "sub": user.login, "user_id": user.id, "email": user.email,
        })
    }


@pytest.fixture(scope="function")
def vendor_for_doc44(db_session):
    v = VendorModel(
        id=str(uuid4()),
        name=f"Vendor-{uuid4().hex[:6]}",
        description="-",
        active=True,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


@pytest.fixture(scope="function")
def project_for_doc44(db_session):
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"UIDAI-PR{uuid4().hex[:14].upper()}",
        name="Doc44 Project",
        description="-",
        active=True,
        public=False,
        status="new",
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _create_body(*, vendor_id, project_ids, login=None, email=None,
                 org_role=None, project_assignments=None,
                 assignments=None, division="tmd1"):
    body = {
        "login": login or f"u-{uuid4().hex[:6]}",
        "email": email or f"u-{uuid4().hex[:6]}@example.com",
        "password": "Pmis@1234",
        "firstName": "Test",
        "lastName": "User",
        "admin": False,
        "vendorId": vendor_id,
        "division": division,
        "projectIds": project_ids,
        "phoneNumber": "9999999999",
    }
    if org_role is not None:
        body["orgRole"] = org_role
    if project_assignments is not None:
        body["projectAssignments"] = project_assignments
    if assignments is not None:
        body["assignments"] = assignments
    return body


# ---------------------------------------------------------------------------
# orgRole derivation (RbacRepository helpers)
# ---------------------------------------------------------------------------

class TestDeriveOrgRole:
    def test_admin_user_returns_admin(self, db_session, admin_user):
        result = RbacRepository(db_session).derive_org_role(admin_user.id)
        assert result == "admin"

    def test_super_admin_user_returns_super_admin(self, db_session):
        sa, _ = _bootstrap_super_admin(db_session)
        result = RbacRepository(db_session).derive_org_role(sa.id)
        assert result == "super_admin"

    def test_user_with_no_role_returns_none(self, db_session, member_user):
        # member_user fixture only carries direct user_permissions, no
        # role rows — so orgRole is None.
        result = RbacRepository(db_session).derive_org_role(member_user.id)
        assert result is None

    def test_priority_picks_highest_tier(
        self, db_session, member_user, project_for_doc44,
    ):
        """A user holding both project_member (project-scoped) and
        admin (global) should project to ``admin`` — the higher tier."""
        admin_role_id = (
            db_session.query(RoleModel).filter(RoleModel.name == "admin")
            .one().id
        )
        pm_role_id = (
            db_session.query(RoleModel).filter(RoleModel.name == "project_member")
            .one().id
        )
        db_session.add(UserRoleAssignmentModel(
            user_id=member_user.id, role_id=admin_role_id,
        ))
        db_session.add(UserRoleAssignmentModel(
            user_id=member_user.id, role_id=pm_role_id,
            project_id=project_for_doc44.id,
        ))
        db_session.commit()
        result = RbacRepository(db_session).derive_org_role(member_user.id)
        assert result == "admin"

    def test_division_member_only_returns_none(
        self, db_session, member_user, project_for_doc44,
    ):
        """division_member is intentionally excluded from the FE's
        orgRole enum — a user holding only that role projects to None."""
        dm_role_id = (
            db_session.query(RoleModel).filter(RoleModel.name == "division_member")
            .one().id
        )
        db_session.add(UserRoleAssignmentModel(
            user_id=member_user.id, role_id=dm_role_id,
            project_id=project_for_doc44.id,
        ))
        db_session.commit()
        result = RbacRepository(db_session).derive_org_role(member_user.id)
        assert result is None


# ---------------------------------------------------------------------------
# Project role map
# ---------------------------------------------------------------------------

class TestProjectRoleMap:
    def test_returns_role_per_project(
        self, db_session, member_user, project_for_doc44,
    ):
        pa_role_id = (
            db_session.query(RoleModel).filter(RoleModel.name == "project_admin")
            .one().id
        )
        db_session.add(UserRoleAssignmentModel(
            user_id=member_user.id, role_id=pa_role_id,
            project_id=project_for_doc44.id,
        ))
        db_session.commit()
        result = RbacRepository(db_session).get_project_role_map(member_user.id)
        assert result.get(project_for_doc44.id) == "project_admin"

    def test_higher_tier_wins_on_same_project(
        self, db_session, member_user, project_for_doc44,
    ):
        pa_role_id = (
            db_session.query(RoleModel).filter(RoleModel.name == "project_admin")
            .one().id
        )
        pm_role_id = (
            db_session.query(RoleModel).filter(RoleModel.name == "project_member")
            .one().id
        )
        db_session.add(UserRoleAssignmentModel(
            user_id=member_user.id, role_id=pa_role_id,
            project_id=project_for_doc44.id,
        ))
        db_session.add(UserRoleAssignmentModel(
            user_id=member_user.id, role_id=pm_role_id,
            project_id=project_for_doc44.id,
        ))
        db_session.commit()
        result = RbacRepository(db_session).get_project_role_map(member_user.id)
        assert result.get(project_for_doc44.id) == "project_admin"


# ---------------------------------------------------------------------------
# format_user_response surfaces orgRole + vendorId + projects[].role
# ---------------------------------------------------------------------------

class TestUserResponseProjection:
    def test_me_includes_org_role_and_vendor_id(
        self, client, admin_user, admin_headers,
    ):
        resp = client.get("/api/v3/users/me", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert "orgRole" in data
        assert data["orgRole"] == "admin"
        assert "vendorId" in data
        # admin_user has no vendor in the fixture; vendorId is None.
        assert data["vendorId"] is None

    def test_login_response_includes_org_role(
        self, client, admin_user, db_session,
    ):
        # Disable 2FA on the user so we hit the single-stage login.
        admin_user.two_factor_enabled = False
        db_session.commit()
        resp = client.post("/api/v3/users/login", json={
            "login": "admin", "password": "admin123",
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        # Either single-stage (access_token + user) or 2FA (ephemeral_token).
        assert "access_token" in data
        assert "user" in data
        assert data["user"].get("orgRole") == "admin"


# ---------------------------------------------------------------------------
# /master/roles displayName
# ---------------------------------------------------------------------------

class TestMasterRolesDisplayName:
    def test_master_roles_carries_display_name(
        self, client, admin_user, admin_headers,
    ):
        resp = client.get(
            "/api/v3/master/roles?pageSize=100", headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        elements = resp.json()["data"]["_embedded"]["elements"]
        names = {r["name"]: r.get("displayName") for r in elements}
        assert names.get("project_admin") == "Project Admin"
        assert names.get("project_member") == "Project Member"
        assert names.get("org_admin") == "Organization Admin"
        assert names.get("admin") == "Admin"
        assert names.get("super_admin") == "Super Admin"


# ---------------------------------------------------------------------------
# POST /users/create with orgRole + projectAssignments (Part C)
# ---------------------------------------------------------------------------

class TestCreateUserWithOrgRole:
    """The FE form posts orgRole + project_ids + projectAssignments in
    one call; the BE creates the user AND the matching role rows in
    a single transaction. Caller-vs-target rules apply per role row."""

    def test_admin_creates_org_admin(
        self, client, admin_user, admin_headers, vendor_for_doc44,
        project_for_doc44, db_session,
    ):
        body = _create_body(
            vendor_id=vendor_for_doc44.id,
            project_ids=[project_for_doc44.id],
            org_role="org_admin",
        )
        resp = client.post(
            "/api/v3/users/create", json=body, headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text
        new_user_id = resp.json()["data"]["id"]
        # Response carries the orgRole projection.
        assert resp.json()["data"]["orgRole"] == "org_admin"
        # Backed by a real org-scoped row.
        rows = (
            db_session.query(UserRoleAssignmentModel)
            .filter(UserRoleAssignmentModel.user_id == new_user_id)
            .all()
        )
        org_admin_id = (
            db_session.query(RoleModel).filter(RoleModel.name == "org_admin")
            .one().id
        )
        assert any(
            r.role_id == org_admin_id
            and r.organization_id == vendor_for_doc44.id
            and r.project_id is None
            for r in rows
        )

    def test_admin_creates_project_admin_with_project_mapping(
        self, client, admin_user, admin_headers, vendor_for_doc44,
        db_session,
    ):
        """Doc 44 round 2: project mapping is no longer per-project-role.
        FE sends projectAssignments as just [{projectId}]; the user's
        role on every mapped project equals their orgRole. Response
        carries projects[] + projectAssignments[] without per-project
        role fields."""
        p1 = ProjectModel(
            id=str(uuid4()), project_code=f"UIDAI-PR{uuid4().hex[:14].upper()}",
            name="P1", description="-", active=True, public=False, status="new",
        )
        p2 = ProjectModel(
            id=str(uuid4()), project_code=f"UIDAI-PR{uuid4().hex[:14].upper()}",
            name="P2", description="-", active=True, public=False, status="new",
        )
        db_session.add_all([p1, p2])
        db_session.commit()

        body = _create_body(
            vendor_id=vendor_for_doc44.id,
            project_ids=[p1.id, p2.id],
            org_role="project_admin",
            project_assignments=[
                {"projectId": p1.id},
                {"projectId": p2.id},
            ],
        )
        resp = client.post(
            "/api/v3/users/create", json=body, headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["orgRole"] == "project_admin"
        # projects[] no longer carries a role field per project.
        for p in data["projects"]:
            assert "role" not in p
        # projectAssignments mirrors project_ids as a flat list.
        pa_ids = sorted(pa["projectId"] for pa in data["projectAssignments"])
        assert pa_ids == sorted([p1.id, p2.id])

    def test_admin_creates_admin_user_no_projects(
        self, client, admin_user, admin_headers, vendor_for_doc44,
    ):
        """Doc 44 round 2: admin tier opened up. An admin caller CAN
        now create another admin user. Pre-doc-44 this was a 403."""
        body = _create_body(
            vendor_id=vendor_for_doc44.id,
            project_ids=[],
            org_role="admin",
        )
        resp = client.post(
            "/api/v3/users/create", json=body, headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["orgRole"] == "admin"

    def test_super_admin_can_create_admin_no_projects(
        self, client, db_session, vendor_for_doc44,
    ):
        sa, headers = _bootstrap_super_admin(db_session)
        body = _create_body(
            vendor_id=vendor_for_doc44.id,
            project_ids=[],
            org_role="admin",
        )
        resp = client.post(
            "/api/v3/users/create", json=body, headers=headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["orgRole"] == "admin"

    def test_admin_cannot_create_super_admin(
        self, client, admin_user, admin_headers, vendor_for_doc44,
    ):
        body = _create_body(
            vendor_id=vendor_for_doc44.id,
            project_ids=[],
            org_role="super_admin",
        )
        resp = client.post(
            "/api/v3/users/create", json=body, headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text

    def test_unknown_org_role_rejected(
        self, client, admin_user, admin_headers, vendor_for_doc44,
        project_for_doc44,
    ):
        body = _create_body(
            vendor_id=vendor_for_doc44.id,
            project_ids=[project_for_doc44.id],
            org_role="bogus_role",
        )
        resp = client.post(
            "/api/v3/users/create", json=body, headers=admin_headers,
        )
        assert resp.status_code == 422, resp.text

    def test_create_is_atomic_on_role_assignment_failure(
        self, client, admin_user, admin_headers, vendor_for_doc44,
    ):
        """When the orgRole is rejected by the caller-vs-target gate,
        the user must NOT be persisted. (Pre-doc-44 the caller could
        end up with a half-created user when role assignment failed
        after the user row was already in.)"""
        login = f"atomic-{uuid4().hex[:6]}"
        body = _create_body(
            login=login,
            email=f"{login}@example.com",
            vendor_id=vendor_for_doc44.id,
            project_ids=[],
            org_role="super_admin",
        )
        resp = client.post(
            "/api/v3/users/create", json=body, headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        # User row must not exist.
        from app.infrastructure.db.models.user import UserModel
        from sqlalchemy.orm import Session as _Session
        # We need a session — pull it from the test client's get_db
        # override. Easiest: re-assert via the API.
        get_resp = client.get(
            "/api/v3/users?pageSize=100", headers=admin_headers,
        )
        logins = [
            u["login"]
            for u in get_resp.json()["data"]["_embedded"]["elements"]
        ]
        assert login not in logins
