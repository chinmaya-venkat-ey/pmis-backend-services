"""Doc 44 round 7 — GET /role-grants/{role_name} matrix lookup.

Returns the static list of role names a caller holding ``role_name``
can grant. Mirrors :func:`can_caller_grant`. Per round 7, super_admin
never appears (DB-only bootstrap).
"""
from app.core.permissions import (
    ADMIN_ROLE_NAME,
    DIVISION_MEMBER_ROLE_NAME,
    ORG_ADMIN_ROLE_NAME,
    PROJECT_ADMIN_ROLE_NAME,
    PROJECT_MEMBER_ROLE_NAME,
    SUPER_ADMIN_ROLE_NAME,
)


# ---------------------------------------------------------------------------
# Pure-function coverage
# ---------------------------------------------------------------------------

class TestGrantableRolesFor:
    """Direct on the static-matrix helper."""

    def test_super_admin_can_grant_everything_except_super_admin(self):
        from app.api.v3.role_assignments.services import grantable_roles_for

        out = grantable_roles_for(SUPER_ADMIN_ROLE_NAME)
        assert ADMIN_ROLE_NAME in out
        assert ORG_ADMIN_ROLE_NAME in out
        assert PROJECT_ADMIN_ROLE_NAME in out
        assert PROJECT_MEMBER_ROLE_NAME in out
        assert DIVISION_MEMBER_ROLE_NAME in out
        # Round 7: super_admin is never grantable through the API.
        assert SUPER_ADMIN_ROLE_NAME not in out

    def test_admin_excludes_admin_and_super_admin(self):
        from app.api.v3.role_assignments.services import grantable_roles_for

        out = grantable_roles_for(ADMIN_ROLE_NAME)
        assert ORG_ADMIN_ROLE_NAME in out
        assert PROJECT_ADMIN_ROLE_NAME in out
        assert PROJECT_MEMBER_ROLE_NAME in out
        assert DIVISION_MEMBER_ROLE_NAME in out
        # Round 5/7: admin can't grant admin or super_admin.
        assert ADMIN_ROLE_NAME not in out
        assert SUPER_ADMIN_ROLE_NAME not in out

    def test_org_admin_grants_three_sub_roles(self):
        from app.api.v3.role_assignments.services import grantable_roles_for

        out = grantable_roles_for(ORG_ADMIN_ROLE_NAME)
        assert set(out) == {
            PROJECT_ADMIN_ROLE_NAME,
            PROJECT_MEMBER_ROLE_NAME,
            DIVISION_MEMBER_ROLE_NAME,
        }

    def test_project_admin_grants_only_project_member(self):
        from app.api.v3.role_assignments.services import grantable_roles_for

        out = grantable_roles_for(PROJECT_ADMIN_ROLE_NAME)
        assert out == [PROJECT_MEMBER_ROLE_NAME]

    def test_leaf_tiers_grant_nothing(self):
        from app.api.v3.role_assignments.services import grantable_roles_for

        assert grantable_roles_for(PROJECT_MEMBER_ROLE_NAME) == []
        assert grantable_roles_for(DIVISION_MEMBER_ROLE_NAME) == []

    def test_unknown_role_yields_empty(self):
        from app.api.v3.role_assignments.services import grantable_roles_for

        assert grantable_roles_for("not_a_real_role") == []
        assert grantable_roles_for("") == []


# ---------------------------------------------------------------------------
# Route coverage
# ---------------------------------------------------------------------------

class TestRoleGrantsEndpoint:
    """GET /api/v3/role-grants/{role_name}"""

    def test_returns_admin_matrix(self, client, admin_headers):
        resp = client.get(
            f"/api/v3/role-grants/{ADMIN_ROLE_NAME}",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["roleName"] == ADMIN_ROLE_NAME
        assert ORG_ADMIN_ROLE_NAME in data["grantableRoles"]
        assert ADMIN_ROLE_NAME not in data["grantableRoles"]
        assert SUPER_ADMIN_ROLE_NAME not in data["grantableRoles"]

    def test_returns_super_admin_matrix(self, client, admin_headers):
        resp = client.get(
            f"/api/v3/role-grants/{SUPER_ADMIN_ROLE_NAME}",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["roleName"] == SUPER_ADMIN_ROLE_NAME
        # Round 7: super_admin can grant admin (and below), but NOT
        # super_admin itself.
        assert ADMIN_ROLE_NAME in data["grantableRoles"]
        assert SUPER_ADMIN_ROLE_NAME not in data["grantableRoles"]

    def test_returns_empty_for_leaf_tier(self, client, admin_headers):
        resp = client.get(
            f"/api/v3/role-grants/{PROJECT_MEMBER_ROLE_NAME}",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["grantableRoles"] == []

    def test_returns_empty_for_unknown_role(self, client, admin_headers):
        """Unknown role name → empty list, not 404 (matrix is open-set)."""
        resp = client.get(
            "/api/v3/role-grants/not_a_real_role",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["roleName"] == "not_a_real_role"
        assert body["grantableRoles"] == []

    def test_requires_authentication(self, client):
        resp = client.get(f"/api/v3/role-grants/{ADMIN_ROLE_NAME}")
        assert resp.status_code in (401, 403)
