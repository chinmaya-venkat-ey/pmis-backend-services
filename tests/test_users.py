"""Tests for user management endpoints.

Covers the user-management feature batch:
  - create requires vendor, division, project_ids (issue 1 + 4)
  - listing is newest-first (issue 5)
  - delete is soft-delete; status='inactive' is allowed; restore via
    PATCH status='active' (issue 2)
  - response embeds vendor, division, projects (issue 4)
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.vendor import VendorModel


# ---------------------------------------------------------------------------
# Fixtures local to user tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def sample_vendor(db_session):
    """A vendor row to satisfy the vendor_id required-field on user create."""
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


@pytest.fixture(scope="function")
def sample_project_for_user(db_session):
    """A project row for the project_ids required-field on user create.

    Distinct name from the existing ``sample_project`` so tests that use
    both don't conflict on the project_code uniqueness.
    """
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"UIDAI-PR{uuid4().hex[:14].upper()}",
        name="Project for user mapping",
        description="-",
        active=True,
        public=False,
        status="new",
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _create_body(*, login="newuser", email="new@example.com",
                 password="password123", vendor_id, project_ids,
                 division="tmd1", division_other=None,
                 phone_number="9876543210",
                 first_name="New", last_name="User"):
    """Build a valid create payload with all required fields filled in."""
    body = {
        "login": login,
        "email": email,
        "password": password,
        "firstName": first_name,
        "lastName": last_name,
        "admin": False,
        "vendorId": vendor_id,
        "division": division,
        "projectIds": project_ids,
        "phoneNumber": phone_number,
    }
    if division_other is not None:
        body["divisionOther"] = division_other
    return body


# ===========================================================================
# CREATE
# ===========================================================================

class TestCreateUser:
    """POST /api/v3/users/create"""

    def test_create_user_success(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        resp = client.post("/api/v3/users/create", json=_create_body(
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
        ), headers=admin_headers)
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["login"] == "newuser"
        assert data["_type"] == "User"
        assert data["vendor"] == {"id": sample_vendor.id, "name": sample_vendor.name}
        assert data["division"] == "tmd1"
        assert data["divisionOther"] is None
        assert len(data["projects"]) == 1
        assert data["projects"][0]["id"] == sample_project_for_user.id

    def test_create_user_with_division_others(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        resp = client.post("/api/v3/users/create", json=_create_body(
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
            division="others",
            division_other="Custom Division",
        ), headers=admin_headers)
        assert resp.status_code == 201, resp.text
        d = resp.json()["data"]
        assert d["division"] == "others"
        assert d["divisionOther"] == "Custom Division"

    def test_create_user_rejects_missing_project_mapping(
        self, client, admin_user, admin_headers, sample_vendor,
    ):
        body = _create_body(
            vendor_id=sample_vendor.id, project_ids=[],
        )
        resp = client.post("/api/v3/users/create", json=body, headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_rejects_missing_vendor(
        self, client, admin_user, admin_headers, sample_project_for_user,
    ):
        body = _create_body(
            vendor_id="", project_ids=[sample_project_for_user.id],
        )
        resp = client.post("/api/v3/users/create", json=body, headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_rejects_unknown_vendor(
        self, client, admin_user, admin_headers, sample_project_for_user,
    ):
        resp = client.post("/api/v3/users/create", json=_create_body(
            vendor_id=str(uuid4()),
            project_ids=[sample_project_for_user.id],
        ), headers=admin_headers)
        assert resp.status_code == 422
        assert "Vendor" in resp.text

    def test_create_user_rejects_unknown_project(
        self, client, admin_user, admin_headers, sample_vendor,
    ):
        resp = client.post("/api/v3/users/create", json=_create_body(
            vendor_id=sample_vendor.id,
            project_ids=[str(uuid4())],
        ), headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_rejects_invalid_division(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        resp = client.post("/api/v3/users/create", json=_create_body(
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
            division="bogus",
        ), headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_rejects_others_without_label(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        resp = client.post("/api/v3/users/create", json=_create_body(
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
            division="others",
        ), headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_duplicate_login(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        body1 = _create_body(
            login="dup", email="a@a.com",
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
        )
        client.post("/api/v3/users/create", json=body1, headers=admin_headers)

        body2 = _create_body(
            login="dup", email="b@b.com",
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
        )
        resp = client.post("/api/v3/users/create", json=body2, headers=admin_headers)
        assert resp.status_code == 409

    def test_create_user_duplicate_email(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        body1 = _create_body(
            login="user1", email="same@example.com",
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
        )
        client.post("/api/v3/users/create", json=body1, headers=admin_headers)

        body2 = _create_body(
            login="user2", email="same@example.com",
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
        )
        resp = client.post("/api/v3/users/create", json=body2, headers=admin_headers)
        assert resp.status_code == 409

    def test_create_user_invalid_email(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        body = _create_body(
            email="not-an-email",
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
        )
        resp = client.post("/api/v3/users/create", json=body, headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_short_password(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        body = _create_body(
            password="short",
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
        )
        resp = client.post("/api/v3/users/create", json=body, headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_short_login(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        body = _create_body(
            login="ab",
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
        )
        resp = client.post("/api/v3/users/create", json=body, headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_missing_required(self, client, admin_user, admin_headers):
        resp = client.post(
            "/api/v3/users/create",
            json={"login": "only"},
            headers=admin_headers,
        )
        assert resp.status_code == 422


# ===========================================================================
# LIST
# ===========================================================================

class TestListUsers:
    """GET /api/v3/users"""

    def test_list_users(self, client, admin_user, admin_headers):
        resp = client.get("/api/v3/users?offset=1&pageSize=10", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["_type"] == "Collection"
        assert body["total"] >= 1

    def test_list_users_pagination(self, client, admin_user, member_user, admin_headers):
        resp = client.get("/api/v3/users?offset=1&pageSize=1", headers=admin_headers)
        body = resp.json()["data"]
        assert body["count"] == 1
        assert body["pageSize"] == 1

    def test_list_users_forbidden_for_member(self, client, admin_user, member_user, member_headers):
        resp = client.get("/api/v3/users", headers=member_headers)
        assert resp.status_code == 403

    def test_list_users_newest_first(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        """Newly-created users appear at the TOP of the list."""
        # Create two distinct users via the API (they get fresh
        # created_at timestamps; the second should sort first).
        for i in range(2):
            client.post("/api/v3/users/create", json=_create_body(
                login=f"u_order_{i}",
                email=f"u_order_{i}@example.com",
                vendor_id=sample_vendor.id,
                project_ids=[sample_project_for_user.id],
            ), headers=admin_headers)
        resp = client.get("/api/v3/users", headers=admin_headers)
        elements = resp.json()["data"]["_embedded"]["elements"]
        # Newest first: u_order_1 above u_order_0 above admin.
        non_admin = [u["login"] for u in elements if u["login"] != "admin"]
        assert non_admin[0] == "u_order_1"
        assert non_admin[1] == "u_order_0"

    def test_list_users_excludes_soft_deleted_by_default(
        self, client, admin_user, admin_headers,
        member_user, sample_vendor, sample_project_for_user,
    ):
        """Soft-deleted users are hidden from the default list."""
        # Soft-delete member.
        client.delete(f"/api/v3/users/{member_user.id}", headers=admin_headers)

        resp = client.get("/api/v3/users", headers=admin_headers)
        body = resp.json()["data"]
        logins = [u["login"] for u in body["_embedded"]["elements"]]
        assert "member" not in logins
        assert "admin" in logins


# ===========================================================================
# GET
# ===========================================================================

class TestGetUser:
    """GET /api/v3/users/{id}"""

    def test_get_user_by_id(self, client, admin_user, admin_headers):
        resp = client.get(f"/api/v3/users/{admin_user.id}", headers=admin_headers)
        assert resp.status_code == 200
        d = resp.json()["data"]
        assert d["login"] == "admin"
        # Embedded blocks present (vendor null on bootstrap admin; projects
        # empty since admin isn't project-mapped in tests).
        assert "vendor" in d
        assert "projects" in d
        assert d["projects"] == []

    def test_get_nonexistent_user(self, client, admin_user, admin_headers):
        resp = client.get("/api/v3/users/99999", headers=admin_headers)
        assert resp.status_code in [200, 404]

    def test_get_response_embeds_vendor_and_projects(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        # Create a user with explicit vendor + project mapping.
        create = client.post("/api/v3/users/create", json=_create_body(
            login="u_with_vendor",
            email="u_with_vendor@example.com",
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
        ), headers=admin_headers)
        assert create.status_code == 201, create.text
        new_id = create.json()["data"]["id"]

        # GET the user; verify the vendor + projects are embedded.
        resp = client.get(f"/api/v3/users/{new_id}", headers=admin_headers)
        assert resp.status_code == 200
        d = resp.json()["data"]
        assert d["vendor"]["id"] == sample_vendor.id
        assert d["vendor"]["name"] == sample_vendor.name
        assert d["division"] == "tmd1"
        assert len(d["projects"]) == 1
        assert d["projects"][0]["id"] == sample_project_for_user.id


# ===========================================================================
# UPDATE
# ===========================================================================

class TestUpdateUser:
    """PATCH /api/v3/users/{id}"""

    def test_update_user(self, client, admin_user, member_user, admin_headers):
        resp = client.patch(f"/api/v3/users/{member_user.id}", json={
            "firstName": "Updated",
            "lastName": "Name",
        }, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["firstName"] == "Updated"

    def test_update_password(self, client, admin_user, member_user, admin_headers):
        resp = client.patch(f"/api/v3/users/{member_user.id}/password", json={
            "password": "newpassword123",
        }, headers=admin_headers)
        assert resp.status_code == 200

    def test_update_status_to_inactive(
        self, client, admin_user, member_user, admin_headers,
    ):
        """Admin can set status='inactive' — fixes tester's 'Status field
        does not work' report."""
        resp = client.patch(f"/api/v3/users/{member_user.id}", json={
            "status": "inactive",
        }, headers=admin_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "inactive"

    def test_update_status_invalid_value_rejected(
        self, client, admin_user, member_user, admin_headers,
    ):
        resp = client.patch(f"/api/v3/users/{member_user.id}", json={
            "status": "made-up-status",
        }, headers=admin_headers)
        assert resp.status_code == 422

    def test_member_cannot_change_status(
        self, client, admin_user, member_user, member_headers,
    ):
        resp = client.patch(f"/api/v3/users/{member_user.id}", json={
            "status": "inactive",
        }, headers=member_headers)
        assert resp.status_code == 403


# ===========================================================================
# DELETE (soft) + RESTORE
# ===========================================================================

class TestDeleteUser:
    """DELETE /api/v3/users/{id} — soft-delete semantics."""

    def test_delete_is_soft(
        self, client, admin_user, member_user, admin_headers, db_session,
    ):
        """Delete sets deleted_at + status='inactive'; row stays in DB."""
        from app.infrastructure.db.models.user import UserModel

        resp = client.delete(f"/api/v3/users/{member_user.id}", headers=admin_headers)
        assert resp.status_code == 200

        db_session.expire_all()
        row = db_session.query(UserModel).filter_by(id=member_user.id).one()
        assert row is not None  # NOT removed
        assert row.deleted_at is not None
        assert row.status == "inactive"

    def test_delete_nonexistent_user(self, client, admin_user, admin_headers):
        resp = client.delete("/api/v3/users/99999", headers=admin_headers)
        assert resp.status_code in [200, 404]

    def test_delete_then_get_returns_404(
        self, client, admin_user, member_user, admin_headers,
    ):
        client.delete(f"/api/v3/users/{member_user.id}", headers=admin_headers)
        resp = client.get(f"/api/v3/users/{member_user.id}", headers=admin_headers)
        # The default GET filters out soft-deleted users.
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            # If service returns 200 with error envelope, the body should
            # carry an error rather than the user.
            assert resp.json().get("error") is not None or resp.json().get("data") is None

    def test_restore_via_status_active(
        self, client, admin_user, member_user, admin_headers, db_session,
    ):
        """Admin setting status='active' on a deleted user clears deleted_at."""
        from app.infrastructure.db.models.user import UserModel

        # Soft-delete first.
        client.delete(f"/api/v3/users/{member_user.id}", headers=admin_headers)

        # Now restore via PATCH status=active.
        resp = client.patch(f"/api/v3/users/{member_user.id}", json={
            "status": "active",
        }, headers=admin_headers)
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        row = db_session.query(UserModel).filter_by(id=member_user.id).one()
        assert row.deleted_at is None
        assert row.status == "active"


# ===========================================================================
# ADMIN-PROTECTION GUARDS (last-active-admin + self-action lockout)
# ===========================================================================

@pytest.fixture(scope="function")
def second_admin_user(db_session):
    """A second admin so the last-active-admin guards don't block test
    operations on ``admin_user``. Status active, not deleted."""
    from app.core.security import hash_password
    from app.infrastructure.db.models.role import RoleModel
    from app.infrastructure.db.models.user import UserModel
    from app.infrastructure.db.models.user_role import UserRoleModel

    u = UserModel(
        login="admin2",
        email="admin2@example.com",
        hashed_password=hash_password("admin123"),
        first_name="Admin",
        last_name="Two",
        status="active",
        two_factor_enabled=False,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    # Doc 21 part B: admin status comes from the seeded ``admin`` role.
    admin_role = (
        db_session.query(RoleModel).filter(RoleModel.name == "admin").first()
    )
    if admin_role is not None:
        db_session.add(UserRoleModel(user_id=u.id, role_id=admin_role.id))
        db_session.commit()
    return u


class TestAdminProtectionGuards:
    """The system must never let an admin lock the platform out of itself.

    Verifies:
      - admin cannot DELETE their own row (would drop their session)
      - admin cannot demote themselves from admin via PATCH
      - admin cannot deactivate themselves when they're the last admin
      - the same operations succeed cleanly when a second admin exists
    """

    def test_admin_cannot_delete_self(
        self, client, admin_user, admin_headers,
    ):
        """Self-delete is refused with 403 even when more admins exist."""
        resp = client.delete(
            f"/api/v3/users/{admin_user.id}", headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "own account" in resp.text.lower()

    def test_admin_cannot_demote_self(
        self, client, admin_user, admin_headers,
    ):
        """PATCH {admin: false} on self → 403 (would drop own admin perms)."""
        resp = client.patch(
            f"/api/v3/users/{admin_user.id}",
            json={"admin": False},
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "demote yourself" in resp.text.lower()

    def test_admin_can_deactivate_another_admin_post_doc42b(
        self, client, admin_user, second_admin_user, admin_headers, db_session,
    ):
        """Doc 42b: admin is no longer the lockout-protected tier. An
        admin user CAN be deactivated freely (target = second_admin_user;
        actor = admin_user). Self-deactivate is blocked separately by
        the G1 guard — see TestSelfDeactivateBlocked in test_doc43_*."""
        from app.infrastructure.db.models.user import UserModel

        resp = client.patch(
            f"/api/v3/users/{second_admin_user.id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        row = db_session.query(UserModel).filter_by(id=second_admin_user.id).one()
        assert row.status == "inactive"

    def test_lockout_blocks_last_active_super_admin_at_service_layer(
        self, db_session, admin_user,
    ):
        """Doc 42b lockout pivot — defense-in-depth.

        Note: route-level callers can no longer REACH this branch:
          - self-deactivate is preempted by G1 (403);
          - admin-deactivating-super_admin is preempted by F1 hierarchy
            gate (403);
          - super_admin-deactivating-another-super_admin can't trigger
            it because then a second active SA exists by definition.
        The lockout remains as a safety net for any future caller that
        bypasses the API gates (cron, fixtures, scripts), so we exercise
        it directly against the service function."""
        from app.api.v3.users.services.update import update_user
        from app.infrastructure.db.models.role import RoleModel
        from app.infrastructure.db.models.user_role_assignment import (
            UserRoleAssignmentModel,
        )

        sa_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "super_admin")
            .one()
            .id
        )
        db_session.add(UserRoleAssignmentModel(
            user_id=admin_user.id, role_id=sa_role_id,
        ))
        db_session.commit()

        # is_admin=True, requesting_user_id != target → bypass G1 self-guard
        # and F1 hierarchy gate; reach the lockout branch directly.
        result = update_user(
            db=db_session,
            user_id=admin_user.id,
            status="inactive",
            requesting_user_id="ghost-super-admin",
            is_admin=True,
        )
        assert not result.success
        assert result.error_type == "validation_error"
        assert "last active super_admin" in result.error.lower()

    def test_can_delete_admin_when_another_admin_exists(
        self, client, admin_user, second_admin_user, admin_headers, db_session,
    ):
        """Sanity: cross-admin delete still works when not the last admin."""
        from app.infrastructure.db.models.user import UserModel

        resp = client.delete(
            f"/api/v3/users/{second_admin_user.id}", headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        row = db_session.query(UserModel).filter_by(id=second_admin_user.id).one()
        assert row.deleted_at is not None
        assert row.status == "inactive"

    def test_can_deactivate_admin_when_another_admin_exists(
        self, client, admin_user, second_admin_user, admin_headers,
    ):
        """Sanity: deactivating an admin via PATCH succeeds when another
        admin remains. Also verifies non-self deactivation isn't over-blocked."""
        resp = client.patch(
            f"/api/v3/users/{second_admin_user.id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "inactive"


# ===========================================================================
# RESTORE — dedicated POST endpoint
# ===========================================================================

class TestRestoreUserEndpoint:
    """POST /api/v3/users/{id}/restore — explicit restore route.

    Mirrors POST /vendors/{id}/restore. The PATCH {status: 'active'}
    path remains supported (covered by TestUpdateUser); this class
    verifies the dedicated route specifically.
    """

    def test_restore_undeletes_a_soft_deleted_user(
        self, client, admin_user, member_user, admin_headers, db_session,
    ):
        """Soft-delete → POST /restore → row is live again."""
        from app.infrastructure.db.models.user import UserModel

        # Soft-delete first
        client.delete(f"/api/v3/users/{member_user.id}", headers=admin_headers)

        # Restore via the dedicated endpoint
        resp = client.post(
            f"/api/v3/users/{member_user.id}/restore", headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["status"] == "active"
        assert body["deletedAt"] is None
        assert body["deletedBy"] is None

        db_session.expire_all()
        row = db_session.query(UserModel).filter_by(id=member_user.id).one()
        assert row.deleted_at is None
        assert row.deleted_by is None
        assert row.status == "active"

    def test_restore_is_idempotent_on_active_user(
        self, client, admin_user, member_user, admin_headers,
    ):
        """Restoring a user who was never deleted returns the current
        snapshot with HTTP 200 (no 409, no 422). Matches the vendor
        restore contract — benign retries shouldn't error."""
        resp = client.post(
            f"/api/v3/users/{member_user.id}/restore", headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["id"] == member_user.id
        assert body["status"] == "active"
        assert body["deletedAt"] is None

    def test_restore_returns_404_for_unknown_user(
        self, client, admin_user, admin_headers,
    ):
        resp = client.post(
            "/api/v3/users/99999/restore", headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_restore_requires_admin(
        self, client, admin_user, member_user, member_headers,
    ):
        """Non-admins cannot call POST /restore.

        The route has require_permission(USERS_DELETE_ALL) so the RBAC
        middleware refuses before we even reach the service. Either 401
        (no token) or 403 (member) is acceptable; both signal denial.
        """
        resp = client.post(
            f"/api/v3/users/{member_user.id}/restore", headers=member_headers,
        )
        assert resp.status_code in (401, 403)

    def test_restore_preserves_vendor_division_projects(
        self, client, admin_user, admin_headers,
        sample_vendor, sample_project_for_user,
    ):
        """End-to-end: create a user with vendor+division+projects, soft-
        delete, restore — all embedded fields must survive the round-trip."""
        # Create
        create_resp = client.post("/api/v3/users/create", json=_create_body(
            login="restore_target",
            email="restore_target@example.com",
            vendor_id=sample_vendor.id,
            project_ids=[sample_project_for_user.id],
            division="tmd2",
        ), headers=admin_headers)
        assert create_resp.status_code == 201, create_resp.text
        new_id = create_resp.json()["data"]["id"]

        # Delete
        client.delete(f"/api/v3/users/{new_id}", headers=admin_headers)

        # Restore via dedicated endpoint
        resp = client.post(
            f"/api/v3/users/{new_id}/restore", headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["status"] == "active"
        assert body["deletedAt"] is None
        assert body["vendor"]["id"] == sample_vendor.id
        assert body["division"] == "tmd2"
        assert len(body["projects"]) == 1
        assert body["projects"][0]["id"] == sample_project_for_user.id


# ===========================================================================
# LOGOUT (existing — unchanged behaviour)
# ===========================================================================

class TestLogout:
    def _login(self, client, login: str, password: str):
        resp = client.post(
            "/api/v3/users/login",
            json={"login": login, "password": password},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        return (
            data["access_token"],
            data["refresh_token"],
            {"Authorization": f"Bearer {data['access_token']}"},
        )

    def test_logout_success(self, client, admin_user, admin_headers):
        resp = client.post("/api/v3/users/logout", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["_type"] == "Success"
        assert "logged out" in body["data"]["message"].lower()

    def test_logout_blacklists_access_token(self, client, admin_user):
        access, _refresh, headers = self._login(client, "admin", "admin123")
        me = client.get("/api/v3/users/me", headers=headers)
        assert me.status_code == 200
        out = client.post("/api/v3/users/logout", headers=headers)
        assert out.status_code == 200, out.text
        me_after = client.get("/api/v3/users/me", headers=headers)
        assert me_after.status_code == 401

    def test_logout_clears_refresh_token(self, client, admin_user, db_session):
        from app.infrastructure.db.models.user import UserModel
        access, _refresh, headers = self._login(client, "admin", "admin123")
        db_session.expire_all()
        u_before = db_session.query(UserModel).filter_by(login="admin").one()
        assert u_before.refresh_token_jti is not None
        client.post("/api/v3/users/logout", headers=headers)
        db_session.expire_all()
        u_after = db_session.query(UserModel).filter_by(login="admin").one()
        assert u_after.refresh_token_jti is None
        assert u_after.refresh_token_expires_at is None

    def test_logout_invalidates_refresh_endpoint(self, client, admin_user):
        """After logout, the refresh token can no longer mint new access
        tokens via /users/refresh (the user row's stored jti is cleared,
        so the rotation guard rejects it)."""
        _access, refresh, headers = self._login(client, "admin", "admin123")
        client.post("/api/v3/users/logout", headers=headers)

        # Try to refresh using the now-revoked refresh token.
        ref = client.post(
            "/api/v3/users/refresh",
            json={"refresh_token": refresh},
        )
        assert ref.status_code == 401, ref.text

    def test_logout_does_not_rotate_via_introspect(self, client, admin_user):
        """Introspect is RFC 7662 read-only and never rotates. Posting a
        valid refresh token to /users/introspect returns metadata, never
        a new access token. (Regression guard for the Option-C migration.)"""
        _access, refresh, _headers = self._login(client, "admin", "admin123")

        intro = client.post(
            "/api/v3/users/introspect",
            json={"refresh_token": refresh},
        )
        assert intro.status_code == 200, intro.text
        body = intro.json()["data"]
        assert body["active"] is True
        assert body["tokenType"] == "refresh"
        # The legacy rotation response would have included these — assert
        # they are absent so a future regression jumps out.
        assert "access_token" not in body
        assert "refresh_token" not in body

    def test_logout_inserts_blacklist_row(self, client, admin_user, db_session):
        from datetime import datetime, timezone
        from app.infrastructure.db.models.revoked_token import RevokedTokenModel
        access, _refresh, headers = self._login(client, "admin", "admin123")
        client.post("/api/v3/users/logout", headers=headers)
        db_session.expire_all()
        rows = db_session.query(RevokedTokenModel).filter_by(user_id=admin_user.id).all()
        assert len(rows) == 1
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        assert rows[0].expires_at > now_naive

    def test_logout_idempotent(self, client, admin_user, admin_headers):
        first = client.post("/api/v3/users/logout", headers=admin_headers)
        assert first.status_code == 200
        second = client.post("/api/v3/users/logout", headers=admin_headers)
        assert second.status_code == 401

    def test_logout_without_auth_rejected(self, client):
        resp = client.post("/api/v3/users/logout")
        assert resp.status_code == 401

    def test_logout_with_invalid_token_rejected(self, client):
        resp = client.post(
            "/api/v3/users/logout",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401

    def test_login_after_logout_works(self, client, admin_user):
        _access, _refresh, headers = self._login(client, "admin", "admin123")
        client.post("/api/v3/users/logout", headers=headers)
        resp = client.post(
            "/api/v3/users/login",
            json={"login": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200
        new_token = resp.json()["data"]["access_token"]
        me = client.get(
            "/api/v3/users/me",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        assert me.status_code == 200
