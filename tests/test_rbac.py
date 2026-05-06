"""Tests for the DB-driven RBAC overhaul (doc 21 part B).

Covers:
- Permission catalog CRUD (admin)
- Role-permission management (assign / replace / revoke)
- Admin-role protection (cannot delete; cannot modify permissions)
- Built-in permission protection (cannot delete)
- User-role assignment + lockout protection on the last admin
- Direct user-permission grants (additive)
- /me/permissions endpoint exposes effective set
- An unprivileged user with a custom-granted permission gains access
"""
import pytest

from app.core.security import create_access_token, hash_password
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_role import UserRoleModel


def _bare_user(db, login):
    """Create a user with NO role assignments and return (user, headers).

    Useful when a test wants to verify that adding a single direct
    permission unlocks a previously-rejected endpoint."""
    u = UserModel(
        login=login,
        email=f"{login}@example.com",
        hashed_password=hash_password("pw1234567"),
        first_name=login.title(),
        last_name="User",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    token = create_access_token({
        "sub": u.login, "user_id": u.id, "email": u.email,
    })
    return u, {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# /me/permissions
# ---------------------------------------------------------------------------

class TestMePermissions:
    def test_admin_sees_full_set(self, client, admin_user, admin_headers):
        resp = client.get("/api/v3/users/me/permissions", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["isAdmin"] is True
        # Should hold every built-in permission code.
        from app.core.permissions import BUILTIN_PERMISSIONS
        codes = {p.code for p in BUILTIN_PERMISSIONS}
        assert codes.issubset(set(body["permissions"]))

    def test_member_sees_member_set_only(self, client, member_user, member_headers):
        resp = client.get(
            "/api/v3/users/me/permissions", headers=member_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["isAdmin"] is False
        assert "projects:create" in body["permissions"]
        # Admin-only management permissions are NOT in member set.
        assert "permissions:manage" not in body["permissions"]
        assert "rbac:assign" not in body["permissions"]


# ---------------------------------------------------------------------------
# Permission catalog CRUD
# ---------------------------------------------------------------------------

class TestPermissionCatalogCRUD:
    def test_list_includes_seeded_codes(self, client, admin_user, admin_headers):
        resp = client.get("/api/v3/permissions?pageSize=500", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        codes = [p["code"] for p in resp.json()["data"]["_embedded"]["elements"]]
        assert "projects:create" in codes
        assert "rbac:assign" in codes

    def test_create_custom_permission(self, client, admin_user, admin_headers):
        resp = client.post(
            "/api/v3/permissions",
            json={
                "code": "custom:do_thing",
                "name": "Do thing",
                "description": "A custom test permission.",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()["data"]
        assert body["code"] == "custom:do_thing"
        assert body["isBuiltin"] is False

    def test_cannot_delete_builtin_permission(
        self, client, admin_user, admin_headers,
    ):
        resp = client.delete(
            "/api/v3/permissions/projects:create", headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text

    def test_can_delete_custom_permission(
        self, client, admin_user, admin_headers,
    ):
        client.post(
            "/api/v3/permissions",
            json={"code": "custom:perm", "name": "X", "description": ""},
            headers=admin_headers,
        )
        resp = client.delete(
            "/api/v3/permissions/custom:perm", headers=admin_headers,
        )
        assert resp.status_code == 204

    def test_member_cannot_create_permission(
        self, client, member_user, member_headers,
    ):
        resp = client.post(
            "/api/v3/permissions",
            json={"code": "custom:bad", "name": "X", "description": ""},
            headers=member_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Role-permission management
# ---------------------------------------------------------------------------

class TestRolePermissionManagement:
    def test_admin_role_permission_set_locked(
        self, client, admin_user, admin_headers, db_session,
    ):
        admin_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "admin")
            .one()
            .id
        )
        # Replace -> 403
        resp = client.put(
            f"/api/v3/roles/{admin_role_id}/permissions",
            json={"permissions": ["projects:create"]},
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        # Revoke a single -> 403
        resp = client.delete(
            f"/api/v3/roles/{admin_role_id}/permissions/projects:create",
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text

    def test_can_replace_member_role_permissions(
        self, client, admin_user, admin_headers, db_session,
    ):
        member_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "member")
            .one()
            .id
        )
        resp = client.put(
            f"/api/v3/roles/{member_role_id}/permissions",
            json={"permissions": ["projects:read", "projects:create"]},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert sorted(body["permissions"]) == [
            "projects:create", "projects:read",
        ]

    def test_replace_with_unknown_code_rejected(
        self, client, admin_user, admin_headers, db_session,
    ):
        member_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "member")
            .one()
            .id
        )
        resp = client.put(
            f"/api/v3/roles/{member_role_id}/permissions",
            json={"permissions": ["bogus:nope"]},
            headers=admin_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Role CRUD protection
# ---------------------------------------------------------------------------

class TestRoleProtection:
    def test_admin_role_cannot_be_deleted(
        self, client, admin_user, admin_headers, db_session,
    ):
        admin_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "admin")
            .one()
            .id
        )
        resp = client.delete(
            f"/api/v3/roles/{admin_role_id}", headers=admin_headers,
        )
        assert resp.status_code == 403

    def test_member_role_can_be_deleted(
        self, client, admin_user, admin_headers, db_session,
    ):
        member_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "member")
            .one()
            .id
        )
        resp = client.delete(
            f"/api/v3/roles/{member_role_id}", headers=admin_headers,
        )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# User-role assignment + lockout
# ---------------------------------------------------------------------------

class TestUserRoleAssignment:
    def test_assign_role_to_user(
        self, client, admin_user, member_user, admin_headers, db_session,
    ):
        viewer_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "viewer")
            .one()
            .id
        )
        resp = client.post(
            f"/api/v3/users/{member_user.id}/roles/{viewer_role_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        names = [r["name"] for r in resp.json()["data"]["roles"]]
        assert "viewer" in names

    def test_cannot_remove_last_admin(
        self, client, admin_user, admin_headers, db_session,
    ):
        admin_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "admin")
            .one()
            .id
        )
        resp = client.delete(
            f"/api/v3/users/{admin_user.id}/roles/{admin_role_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "last user" in resp.json()["error"]["message"].lower()

    def test_can_remove_admin_role_when_other_admin_exists(
        self, client, admin_user, admin_headers, db_session,
    ):
        # Create a SECOND admin first.
        u, _ = _bare_user(db_session, "admin2")
        admin_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "admin")
            .one()
            .id
        )
        db_session.add(UserRoleModel(user_id=u.id, role_id=admin_role_id))
        db_session.commit()
        # Now the original admin can be unassigned.
        resp = client.delete(
            f"/api/v3/users/{admin_user.id}/roles/{admin_role_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Direct user-permission grants
# ---------------------------------------------------------------------------

class TestDirectUserPermissions:
    def test_direct_permission_grants_access(
        self, client, admin_user, admin_headers, db_session,
    ):
        # User-mgmt doesn't host the /api/v3/projects route. Verify the
        # permission grant + /me/permissions reflection only — the
        # project-create assertion belongs to the monolith's test suite.
        bare, headers = _bare_user(db_session, "noperms")
        resp = client.post(
            f"/api/v3/users/{bare.id}/permissions/projects:create",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        me = client.get("/api/v3/users/me/permissions", headers=headers)
        assert "projects:create" in me.json()["data"]["permissions"]

    def test_revoke_direct_permission(
        self, client, admin_user, admin_headers, db_session,
    ):
        bare, headers = _bare_user(db_session, "noperms2")
        client.post(
            f"/api/v3/users/{bare.id}/permissions/projects:read",
            headers=admin_headers,
        )
        resp = client.delete(
            f"/api/v3/users/{bare.id}/permissions/projects:read",
            headers=admin_headers,
        )
        assert resp.status_code == 204
        me = client.get("/api/v3/users/me/permissions", headers=headers)
        assert "projects:read" not in me.json()["data"]["permissions"]


# ---------------------------------------------------------------------------
# Master-router relocation (doc 21B follow-up)
# ---------------------------------------------------------------------------

class TestMasterRouterRolesPermissions:
    """Roles + permission catalog CRUD now lives under /api/v3/master/*.

    Legacy /api/v3/roles/* and /api/v3/permissions/* keep working with
    Deprecation: true headers — same pattern as vendors and divisions.
    """

    def test_master_roles_list_works(self, client, admin_user, admin_headers):
        resp = client.get("/api/v3/master/roles", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        # New surface — no Deprecation header.
        assert "Deprecation" not in resp.headers
        names = [
            r["name"]
            for r in resp.json()["data"]["_embedded"]["elements"]
        ]
        assert "admin" in names

    def test_master_permissions_list_works(self, client, admin_user, admin_headers):
        resp = client.get(
            "/api/v3/master/permissions?pageSize=500", headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        assert "Deprecation" not in resp.headers
        codes = [
            p["code"]
            for p in resp.json()["data"]["_embedded"]["elements"]
        ]
        assert "projects:create" in codes

    def test_master_create_role_then_replace_permissions(
        self, client, admin_user, admin_headers,
    ):
        created = client.post(
            "/api/v3/master/roles/create",
            json={
                "name": "auditor",
                "description": "read-only auditor",
                "permissions": [],
            },
            headers=admin_headers,
        )
        assert created.status_code == 201, created.text
        rid = created.json()["data"]["id"]

        resp = client.put(
            f"/api/v3/master/roles/{rid}/permissions",
            json={"permissions": ["projects:read", "milestones:read"]},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        assert sorted(resp.json()["data"]["permissions"]) == sorted([
            "milestones:read", "projects:read",
        ])

    def test_master_create_custom_permission(
        self, client, admin_user, admin_headers,
    ):
        resp = client.post(
            "/api/v3/master/permissions/create",
            json={
                "code": "custom:thing",
                "name": "Do thing",
                "description": "Test perm via master.",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["isBuiltin"] is False

    def test_legacy_roles_endpoints_stamp_deprecation(
        self, client, admin_user, admin_headers,
    ):
        resp = client.get("/api/v3/roles", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"
        assert "/api/v3/master/roles" in resp.headers.get("Link", "")

    def test_legacy_permissions_endpoints_stamp_deprecation(
        self, client, admin_user, admin_headers,
    ):
        resp = client.get("/api/v3/permissions", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"
        assert "/api/v3/master/permissions" in resp.headers.get("Link", "")

    def test_admin_role_protection_preserved_on_master_path(
        self, client, admin_user, admin_headers, db_session,
    ):
        from app.infrastructure.db.models.role import RoleModel
        admin_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "admin")
            .one()
            .id
        )
        resp = client.delete(
            f"/api/v3/master/roles/{admin_role_id}", headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text

    def test_master_path_admin_role_perms_locked(
        self, client, admin_user, admin_headers, db_session,
    ):
        from app.infrastructure.db.models.role import RoleModel
        admin_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "admin")
            .one()
            .id
        )
        resp = client.put(
            f"/api/v3/master/roles/{admin_role_id}/permissions",
            json={"permissions": ["projects:create"]},
            headers=admin_headers,
        )
        assert resp.status_code == 403
