"""Doc 41 — scoped RBAC tests.

Three layers of coverage:

  * **Repo tests** (TestScopedAssignmentRepo): direct on ``RbacRepository``.
    Round-trip for create / list / revoke; uniqueness on (user, role,
    scope); the per-scope effective-permissions view; check-constraint
    rejects two-scope rows.

  * **Service tests** (TestCallerVsTargetGate): pure-function coverage
    of the caller-vs-target rules in
    ``app/api/v3/role_assignments/services.py::can_caller_grant``.

  * **Route tests** (TestUserRouteSurface / TestProjectRouteSurface /
    TestVendorProjectsView): end-to-end. Hit the FastAPI client with
    admin / member / unprivileged tokens and assert the matrix.
"""
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.permissions import (
    ADMIN_ROLE_NAME,
    DIVISION_MEMBER_ROLE_NAME,
    ORG_ADMIN_ROLE_NAME,
    PROJECT_ADMIN_ROLE_NAME,
    PROJECT_MEMBER_ROLE_NAME,
    SUPER_ADMIN_ROLE_NAME,
)
from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.project_vendor import ProjectVendorModel
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from app.infrastructure.db.models.vendor import VendorModel
from app.infrastructure.db.repositories.rbac_repository import RbacRepository


def _role_id(db: Session, name: str) -> int:
    return db.query(RoleModel).filter(RoleModel.name == name).first().id


def _make_vendor(db: Session, *, name: str = "TestVendor") -> VendorModel:
    v = VendorModel(
        id=str(uuid4()),
        name=f"{name}-{uuid4().hex[:6]}",
    )
    db.add(v)
    db.commit()
    return v


def _make_project(db: Session, *, name: str = "TestProj") -> ProjectModel:
    p = ProjectModel(
        id=str(uuid4()),
        # Hand-roll a unique project_code; the live generator lives in
        # monolith — user-mgmt only mirrors the model schema for FK
        # validation, so anything unique satisfies the NOT NULL.
        project_code=f"PR-{uuid4().hex[:8].upper()}",
        name=f"{name}-{uuid4().hex[:6]}",
        status="new",
    )
    db.add(p)
    db.commit()
    return p


def _link_vendor_project(db: Session, vendor: VendorModel, project: ProjectModel):
    db.add(ProjectVendorModel(project_id=project.id, vendor_id=vendor.id))
    db.commit()


# ---------------------------------------------------------------------------
# Repo-level tests
# ---------------------------------------------------------------------------

class TestScopedAssignmentRepo:
    """Direct RbacRepository coverage."""

    def test_assign_global_scope(self, db_session, admin_user):
        repo = RbacRepository(db_session)
        role_id = _role_id(db_session, PROJECT_MEMBER_ROLE_NAME)
        row = repo.assign_scoped_role(
            user_id=admin_user.id, role_id=role_id,
            organization_id=None, project_id=None,
        )
        assert row is not None
        assert row.organization_id is None and row.project_id is None

    def test_assign_project_scope(self, db_session, admin_user):
        repo = RbacRepository(db_session)
        proj = _make_project(db_session)
        row = repo.assign_scoped_role(
            user_id=admin_user.id,
            role_id=_role_id(db_session, PROJECT_ADMIN_ROLE_NAME),
            project_id=proj.id,
        )
        assert row.project_id == proj.id and row.organization_id is None

    def test_assign_org_scope(self, db_session, admin_user):
        repo = RbacRepository(db_session)
        v = _make_vendor(db_session)
        row = repo.assign_scoped_role(
            user_id=admin_user.id,
            role_id=_role_id(db_session, ORG_ADMIN_ROLE_NAME),
            organization_id=v.id,
        )
        assert row.organization_id == v.id and row.project_id is None

    def test_two_scopes_at_once_raises(self, db_session, admin_user):
        repo = RbacRepository(db_session)
        v = _make_vendor(db_session)
        p = _make_project(db_session)
        with pytest.raises(ValueError):
            repo.assign_scoped_role(
                user_id=admin_user.id,
                role_id=_role_id(db_session, PROJECT_ADMIN_ROLE_NAME),
                organization_id=v.id,
                project_id=p.id,
            )

    def test_idempotent_on_duplicate(self, db_session, admin_user):
        repo = RbacRepository(db_session)
        proj = _make_project(db_session)
        role_id = _role_id(db_session, PROJECT_MEMBER_ROLE_NAME)
        first = repo.assign_scoped_role(
            user_id=admin_user.id, role_id=role_id, project_id=proj.id,
        )
        second = repo.assign_scoped_role(
            user_id=admin_user.id, role_id=role_id, project_id=proj.id,
        )
        assert first.id == second.id  # same row returned

    def test_effective_permissions_by_scope(self, db_session, member_user):
        """Project-scoped permissions land in the project bucket; legacy
        user_roles rows land in the global bucket."""
        repo = RbacRepository(db_session)
        proj = _make_project(db_session)
        repo.assign_scoped_role(
            user_id=member_user.id,
            role_id=_role_id(db_session, PROJECT_MEMBER_ROLE_NAME),
            project_id=proj.id,
        )
        db_session.commit()

        scoped = repo.effective_permissions_by_scope(member_user.id)
        # member_user has the legacy 'member' role assigned via user_roles
        assert ("global", None) in scoped
        # plus the new project-scoped row
        assert ("project", proj.id) in scoped
        # and the union still contains everything the role grants
        flat = repo.effective_permissions_for_user(member_user.id)
        assert "tasks:read" in flat  # member role grants this

    def test_revoke_round_trip(self, db_session, admin_user):
        repo = RbacRepository(db_session)
        proj = _make_project(db_session)
        row = repo.assign_scoped_role(
            user_id=admin_user.id,
            role_id=_role_id(db_session, PROJECT_ADMIN_ROLE_NAME),
            project_id=proj.id,
        )
        db_session.commit()
        ok = repo.revoke_scoped_assignment(row.id)
        db_session.commit()
        assert ok is True
        assert repo.get_scoped_assignment(row.id) is None

    def test_user_has_admin_role_via_legacy(self, db_session, admin_user):
        repo = RbacRepository(db_session)
        # admin_user fixture used the legacy user_roles path
        assert repo.user_has_admin_role(admin_user.id) is True

    def test_user_has_admin_role_via_scoped_global(self, db_session, member_user):
        """A scoped-global super_admin row also makes the user 'admin'."""
        repo = RbacRepository(db_session)
        repo.assign_scoped_role(
            user_id=member_user.id,
            role_id=_role_id(db_session, SUPER_ADMIN_ROLE_NAME),
            organization_id=None, project_id=None,
        )
        db_session.commit()
        assert repo.user_has_admin_role(member_user.id) is True
        assert repo.user_has_super_admin_role(member_user.id) is True


# ---------------------------------------------------------------------------
# Service-level: caller-vs-target gate
# ---------------------------------------------------------------------------

class TestCallerVsTargetGate:
    """Direct on the can_caller_grant pure helper.

    Sets up minimal scoped-role rows for the caller and asserts the
    grant decisions match the doc 41 rule table.
    """

    def test_admin_can_grant_anything_except_super_admin(
        self, db_session, admin_user,
    ):
        from app.api.v3.role_assignments.services import can_caller_grant
        # admin_user holds the legacy 'admin' role.
        for target in (
            ORG_ADMIN_ROLE_NAME, PROJECT_ADMIN_ROLE_NAME,
            PROJECT_MEMBER_ROLE_NAME, DIVISION_MEMBER_ROLE_NAME,
        ):
            allowed, _ = can_caller_grant(
                db_session, admin_user.id,
                target_role_name=target,
                target_organization_id=None,
                target_project_id=str(uuid4()),
            )
            assert allowed, f"admin should be able to grant {target}"

        # super_admin granting requires super_admin
        allowed, reason = can_caller_grant(
            db_session, admin_user.id,
            target_role_name=SUPER_ADMIN_ROLE_NAME,
            target_organization_id=None,
            target_project_id=None,
        )
        assert not allowed and "super_admin" in reason

    def test_super_admin_can_grant_super_admin(
        self, db_session, admin_user,
    ):
        from app.api.v3.role_assignments.services import can_caller_grant
        # Promote admin to super_admin via scoped-global assignment.
        RbacRepository(db_session).assign_scoped_role(
            user_id=admin_user.id,
            role_id=_role_id(db_session, SUPER_ADMIN_ROLE_NAME),
            organization_id=None, project_id=None,
        )
        db_session.commit()
        allowed, _ = can_caller_grant(
            db_session, admin_user.id,
            target_role_name=SUPER_ADMIN_ROLE_NAME,
            target_organization_id=None,
            target_project_id=None,
        )
        assert allowed

    def test_org_admin_can_grant_within_their_vendor(
        self, db_session, member_user,
    ):
        """org_admin of vendor X can grant project-scoped roles on
        projects whose owning vendor is X."""
        from app.api.v3.role_assignments.services import can_caller_grant
        v = _make_vendor(db_session)
        proj = _make_project(db_session)
        _link_vendor_project(db_session, v, proj)
        # Make member_user an org_admin of v.
        RbacRepository(db_session).assign_scoped_role(
            user_id=member_user.id,
            role_id=_role_id(db_session, ORG_ADMIN_ROLE_NAME),
            organization_id=v.id,
        )
        db_session.commit()
        allowed, _ = can_caller_grant(
            db_session, member_user.id,
            target_role_name=PROJECT_MEMBER_ROLE_NAME,
            target_organization_id=None,
            target_project_id=proj.id,
        )
        assert allowed

    def test_org_admin_cannot_grant_outside_vendor(
        self, db_session, member_user,
    ):
        from app.api.v3.role_assignments.services import can_caller_grant
        v_mine = _make_vendor(db_session)
        v_other = _make_vendor(db_session)
        proj_other = _make_project(db_session)
        _link_vendor_project(db_session, v_other, proj_other)
        RbacRepository(db_session).assign_scoped_role(
            user_id=member_user.id,
            role_id=_role_id(db_session, ORG_ADMIN_ROLE_NAME),
            organization_id=v_mine.id,
        )
        db_session.commit()
        allowed, _ = can_caller_grant(
            db_session, member_user.id,
            target_role_name=PROJECT_MEMBER_ROLE_NAME,
            target_organization_id=None,
            target_project_id=proj_other.id,
        )
        assert not allowed

    def test_project_admin_can_only_grant_project_member(
        self, db_session, member_user,
    ):
        from app.api.v3.role_assignments.services import can_caller_grant
        proj = _make_project(db_session)
        RbacRepository(db_session).assign_scoped_role(
            user_id=member_user.id,
            role_id=_role_id(db_session, PROJECT_ADMIN_ROLE_NAME),
            project_id=proj.id,
        )
        db_session.commit()
        # Allowed: project_member on the same project.
        allowed, _ = can_caller_grant(
            db_session, member_user.id,
            target_role_name=PROJECT_MEMBER_ROLE_NAME,
            target_organization_id=None,
            target_project_id=proj.id,
        )
        assert allowed
        # Denied: project_admin (cannot grant peers).
        allowed, _ = can_caller_grant(
            db_session, member_user.id,
            target_role_name=PROJECT_ADMIN_ROLE_NAME,
            target_organization_id=None,
            target_project_id=proj.id,
        )
        assert not allowed

    def test_unprivileged_user_grants_nothing(
        self, db_session, member_user,
    ):
        """A bare 'member' (legacy role only) cannot grant any doc-41 role."""
        from app.api.v3.role_assignments.services import can_caller_grant
        proj = _make_project(db_session)
        # member_user still has only the legacy 'member' role.
        allowed, _ = can_caller_grant(
            db_session, member_user.id,
            target_role_name=PROJECT_MEMBER_ROLE_NAME,
            target_organization_id=None,
            target_project_id=proj.id,
        )
        assert not allowed


# ---------------------------------------------------------------------------
# Route-level tests
# ---------------------------------------------------------------------------

class TestUserRoleAssignmentsEndpoint:
    """Hit /api/v3/users/{id}/role-assignments end-to-end."""

    def test_admin_can_grant_project_member(
        self, client, admin_headers, db_session, admin_user, member_user,
    ):
        proj = _make_project(db_session)
        body = {
            "roleId": _role_id(db_session, PROJECT_MEMBER_ROLE_NAME),
            "projectId": proj.id,
        }
        resp = client.post(
            f"/api/v3/users/{member_user.id}/role-assignments",
            json=body, headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["userId"] == member_user.id
        assert data["roleName"] == PROJECT_MEMBER_ROLE_NAME
        assert data["projectId"] == proj.id
        assert data["scope"] == "project"

    def test_member_cannot_grant(
        self, client, member_headers, db_session, admin_user,
    ):
        proj = _make_project(db_session)
        body = {
            "roleId": _role_id(db_session, PROJECT_MEMBER_ROLE_NAME),
            "projectId": proj.id,
        }
        resp = client.post(
            f"/api/v3/users/{admin_user.id}/role-assignments",
            json=body, headers=member_headers,
        )
        # 403 (RBAC_ASSIGN gate fails for member role).
        assert resp.status_code == 403, resp.text

    def test_list_returns_scoped_assignments(
        self, client, admin_headers, db_session, admin_user, member_user,
    ):
        proj = _make_project(db_session)
        RbacRepository(db_session).assign_scoped_role(
            user_id=member_user.id,
            role_id=_role_id(db_session, PROJECT_MEMBER_ROLE_NAME),
            project_id=proj.id,
        )
        db_session.commit()
        resp = client.get(
            f"/api/v3/users/{member_user.id}/role-assignments",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        assert any(
            i["projectId"] == proj.id and i["roleName"] == PROJECT_MEMBER_ROLE_NAME
            for i in items
        )

    def test_user_can_read_own_assignments(
        self, client, member_headers, db_session, member_user,
    ):
        proj = _make_project(db_session)
        RbacRepository(db_session).assign_scoped_role(
            user_id=member_user.id,
            role_id=_role_id(db_session, PROJECT_MEMBER_ROLE_NAME),
            project_id=proj.id,
        )
        db_session.commit()
        resp = client.get(
            f"/api/v3/users/{member_user.id}/role-assignments",
            headers=member_headers,
        )
        assert resp.status_code == 200, resp.text

    def test_member_cannot_read_others_assignments(
        self, client, member_headers, admin_user,
    ):
        resp = client.get(
            f"/api/v3/users/{admin_user.id}/role-assignments",
            headers=member_headers,
        )
        assert resp.status_code == 403, resp.text

    def test_delete_round_trip(
        self, client, admin_headers, db_session, member_user,
    ):
        proj = _make_project(db_session)
        repo = RbacRepository(db_session)
        row = repo.assign_scoped_role(
            user_id=member_user.id,
            role_id=_role_id(db_session, PROJECT_MEMBER_ROLE_NAME),
            project_id=proj.id,
        )
        db_session.commit()
        resp = client.delete(
            f"/api/v3/users/{member_user.id}/role-assignments/{row.id}",
            headers=admin_headers,
        )
        assert resp.status_code == 204, resp.text
        assert repo.get_scoped_assignment(row.id) is None


class TestProjectRoleAssignmentsEndpoint:
    """Hit /api/v3/projects/{id}/role-assignments end-to-end."""

    def test_grouped_view_returns_per_role_buckets(
        self, client, admin_headers, db_session, admin_user, member_user,
    ):
        proj = _make_project(db_session)
        RbacRepository(db_session).assign_scoped_role(
            user_id=member_user.id,
            role_id=_role_id(db_session, PROJECT_MEMBER_ROLE_NAME),
            project_id=proj.id,
        )
        db_session.commit()
        resp = client.get(
            f"/api/v3/projects/{proj.id}/role-assignments",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["projectId"] == proj.id
        roles = data["roles"]
        bucket = next(r for r in roles if r["roleName"] == PROJECT_MEMBER_ROLE_NAME)
        assert any(u["id"] == member_user.id for u in bucket["users"])

    def test_admin_creates_via_project_path(
        self, client, admin_headers, db_session, member_user,
    ):
        proj = _make_project(db_session)
        body = {
            "userId": member_user.id,
            "roleId": _role_id(db_session, PROJECT_MEMBER_ROLE_NAME),
        }
        resp = client.post(
            f"/api/v3/projects/{proj.id}/role-assignments",
            json=body, headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["projectId"] == proj.id

    def test_post_without_user_id_rejected(
        self, client, admin_headers, db_session,
    ):
        proj = _make_project(db_session)
        body = {"roleId": _role_id(db_session, PROJECT_MEMBER_ROLE_NAME)}
        resp = client.post(
            f"/api/v3/projects/{proj.id}/role-assignments",
            json=body, headers=admin_headers,
        )
        assert resp.status_code == 422


class TestVendorProjectsView:
    """Hit /api/v3/vendors/{id}/projects end-to-end."""

    def test_lists_projects_for_vendor(
        self, client, admin_headers, db_session,
    ):
        v = _make_vendor(db_session)
        p = _make_project(db_session)
        _link_vendor_project(db_session, v, p)
        resp = client.get(
            f"/api/v3/vendors/{v.id}/projects",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert any(row["projectId"] == p.id for row in data["projects"])

    def test_expand_role_assignments_inlines_buckets(
        self, client, admin_headers, db_session, member_user,
    ):
        v = _make_vendor(db_session)
        p = _make_project(db_session)
        _link_vendor_project(db_session, v, p)
        RbacRepository(db_session).assign_scoped_role(
            user_id=member_user.id,
            role_id=_role_id(db_session, PROJECT_MEMBER_ROLE_NAME),
            project_id=p.id,
        )
        db_session.commit()
        resp = client.get(
            f"/api/v3/vendors/{v.id}/projects?expand=role-assignments",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        row = next(
            r for r in resp.json()["data"]["projects"] if r["projectId"] == p.id
        )
        assert "roleAssignments" in row
        assert any(
            b["roleName"] == PROJECT_MEMBER_ROLE_NAME
            for b in row["roleAssignments"]
        )

    def test_unknown_vendor_returns_404(self, client, admin_headers):
        bogus = str(uuid4())
        resp = client.get(
            f"/api/v3/vendors/{bogus}/projects",
            headers=admin_headers,
        )
        assert resp.status_code == 404
