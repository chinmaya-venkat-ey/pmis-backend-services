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
    def test_admin_sees_full_set_minus_grant_superadmin(
        self, client, admin_user, admin_headers,
    ):
        """admin holds every built-in permission EXCEPT
        users:grant_superadmin (post-doc-42b demotion). The exclusion
        is what stops admin from promoting users to super_admin."""
        resp = client.get("/api/v3/users/me/permissions", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["isAdmin"] is True
        from app.core.permissions import (
            BUILTIN_PERMISSIONS, USERS_GRANT_SUPERADMIN,
        )
        all_codes = {p.code for p in BUILTIN_PERMISSIONS}
        expected = all_codes - {USERS_GRANT_SUPERADMIN}
        actual = set(body["permissions"])
        assert expected.issubset(actual), (
            f"admin missing codes: {expected - actual}"
        )
        assert USERS_GRANT_SUPERADMIN not in actual, (
            "admin must NOT hold users:grant_superadmin"
        )

    def test_member_sees_baseline_set_only(self, client, member_user, member_headers):
        """Post-doc-43-round-4 the 'member' role is gone; the
        ``member_user`` fixture grants a baseline set as direct
        user_permissions instead. The /me/permissions surface still
        unions direct grants with role-derived perms, so this test
        verifies the baseline is visible and admin-only codes are not."""
        resp = client.get(
            "/api/v3/users/me/permissions", headers=member_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["isAdmin"] is False
        assert "projects:create" in body["permissions"]
        # Admin-only management permissions are NOT in baseline set.
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

    def test_can_replace_custom_role_permissions(
        self, client, admin_user, admin_headers, db_session,
    ):
        """Replace the entire permission set on a custom (non-builtin)
        role — admin / super_admin role rows are locked, so we make
        a custom role first."""
        create = client.post(
            "/api/v3/master/roles/create",
            json={"name": "test_replaceable_role",
                  "description": "test role"},
            headers=admin_headers,
        )
        assert create.status_code == 201, create.text
        role_id = create.json()["data"]["id"]

        resp = client.put(
            f"/api/v3/roles/{role_id}/permissions",
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
        create = client.post(
            "/api/v3/master/roles/create",
            json={"name": "test_unknown_code_role",
                  "description": "test role"},
            headers=admin_headers,
        )
        assert create.status_code == 201, create.text
        role_id = create.json()["data"]["id"]
        resp = client.put(
            f"/api/v3/roles/{role_id}/permissions",
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

    def test_custom_role_can_be_deleted(
        self, client, admin_user, admin_headers, db_session,
    ):
        """Custom (non-builtin) roles can be deleted via the master
        endpoint. Contrast with the admin / super_admin role rows
        which are locked."""
        create = client.post(
            "/api/v3/master/roles/create",
            json={"name": "test_deletable_role",
                  "description": "test role"},
            headers=admin_headers,
        )
        assert create.status_code == 201, create.text
        role_id = create.json()["data"]["id"]
        resp = client.delete(
            f"/api/v3/roles/{role_id}", headers=admin_headers,
        )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# User-role assignment + lockout
# ---------------------------------------------------------------------------

class TestUserRoleAssignment:
    def test_assign_role_to_user(
        self, client, admin_user, member_user, admin_headers, db_session,
    ):
        """Assign a custom test role to a user via the legacy
        per-user-role endpoint. (The seeded 'viewer' role this test
        used pre-doc-43-round-4 is gone; create a custom one.)"""
        create = client.post(
            "/api/v3/master/roles/create",
            json={"name": "test_assignable_role",
                  "description": "test role"},
            headers=admin_headers,
        )
        assert create.status_code == 201, create.text
        role_id = create.json()["data"]["id"]
        resp = client.post(
            f"/api/v3/users/{member_user.id}/roles/{role_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        names = [r["name"] for r in resp.json()["data"]["roles"]]
        assert "test_assignable_role" in names

    def test_admin_caller_can_remove_admin_role_post_doc44(
        self, client, admin_user, admin_headers, db_session,
        second_admin_user,
    ):
        """Doc 44 round 2: admin tier opened up. Symmetric grant +
        revoke matrix means an admin caller CAN now revoke the admin
        role from another admin. (Pre-doc-44 only super_admin could.)
        Self-revoke is still blocked by the existing self-demote
        guard, so we revoke from a different admin user."""
        admin_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "admin")
            .one()
            .id
        )
        resp = client.delete(
            f"/api/v3/users/{second_admin_user.id}/roles/{admin_role_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 204, resp.text

    def test_super_admin_caller_can_remove_admin_role(
        self, client, admin_user, db_session,
    ):
        """Symmetric to the demotion: a super_admin caller can freely
        revoke the admin role from any user — admin is no longer the
        protected tier, super_admin is. We don't test the 'last admin'
        case anymore because admin has no lockout post-doc-42b."""
        from app.core.security import create_access_token
        from app.infrastructure.db.models.user_role_assignment import (
            UserRoleAssignmentModel,
        )
        # Create a super_admin caller via the doc-41 assignments table.
        sa_user, _ = _bare_user(db_session, "sa-caller")
        sa_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "super_admin")
            .one()
            .id
        )
        db_session.add(UserRoleAssignmentModel(
            user_id=sa_user.id, role_id=sa_role_id,
        ))
        db_session.commit()
        sa_headers = {"Authorization": f"Bearer " + create_access_token({
            "sub": sa_user.login, "user_id": sa_user.id, "email": sa_user.email,
        })}

        admin_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "admin")
            .one()
            .id
        )
        resp = client.delete(
            f"/api/v3/users/{admin_user.id}/roles/{admin_role_id}",
            headers=sa_headers,
        )
        assert resp.status_code == 204, resp.text


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
