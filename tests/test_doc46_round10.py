"""Doc 46 round 10 — three tester-feedback BE fixes.

#3  ``orgRole`` is now required on POST /users/create + validated to
    one of the six FE-known role names.
#4  New endpoint ``GET /api/v3/users/check-login?login=…`` returns
    ``{login, available}`` — wraps ``UserRepository.exists_by_login``
    so the FE can debounce uniqueness in real-time.
#6/#13 ``GET /api/v3/users`` excludes admin / super_admin users
    when the caller is non-admin (org_admin / project_admin). Closes
    the leak where PMIS-Admin candidates surfaced in OA's User Mgmt
    list and Assign-To dropdowns.
"""
from uuid import uuid4

import pytest

from app.core.security import create_access_token, hash_password
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_role import UserRoleModel
from app.infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from app.infrastructure.db.models.vendor import VendorModel
from app.infrastructure.db.repositories.rbac_repository import RbacRepository


@pytest.fixture
def shared_vendor(db_session):
    v = VendorModel(
        id=str(uuid4()),
        name=f"Vendor-{uuid4().hex[:6]}",
        description="-", active=True,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


def _create_body(login, vendor_id, **overrides):
    body = {
        "login": login,
        "email": f"{login}@example.com",
        "password": "Pmis@1234",
        "firstName": "T", "lastName": "U",
        "phoneNumber": "+919999999999",
        "division": "tmd1",
        "vendorId": vendor_id,
        "project_ids": [],
        "orgRole": "project_member",
    }
    body.update(overrides)
    return body


def _make_user(db_session, login, vendor_id):
    u = UserModel(
        login=f"{login}-{uuid4().hex[:5]}",
        email=f"{login}-{uuid4().hex[:5]}@example.com",
        hashed_password=hash_password("Pmis@1234"),
        first_name="T", last_name="U",
        status="active", two_factor_enabled=False,
        vendor_id=vendor_id,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _grant_admin_legacy(db_session, user):
    role = (
        db_session.query(RoleModel)
        .filter(RoleModel.name == "admin").one()
    )
    db_session.add(UserRoleModel(user_id=user.id, role_id=role.id))
    db_session.commit()


def _grant_super_admin_scoped(db_session, user):
    role = (
        db_session.query(RoleModel)
        .filter(RoleModel.name == "super_admin").one()
    )
    db_session.add(UserRoleAssignmentModel(
        user_id=user.id, role_id=role.id,
    ))
    db_session.commit()


def _make_oa(db_session, login, vendor_id):
    """Return (user, headers) for an org_admin scoped to ``vendor_id``."""
    RbacRepository(db_session).sync_builtin_permissions()
    db_session.commit()
    role = (
        db_session.query(RoleModel)
        .filter(RoleModel.name == "org_admin").one()
    )
    user = _make_user(db_session, login, vendor_id)
    db_session.add(UserRoleAssignmentModel(
        user_id=user.id, role_id=role.id, organization_id=vendor_id,
    ))
    db_session.commit()
    return user, {
        "Authorization": "Bearer " + create_access_token({
            "sub": user.login, "user_id": user.id, "email": user.email,
        })
    }


# ---------------------------------------------------------------------------
# #3 — orgRole required + validated
# ---------------------------------------------------------------------------

class TestOrgRoleRequiredOnCreate:
    def test_missing_orgrole_returns_422(
        self, client, admin_user, admin_headers, shared_vendor,
    ):
        body = _create_body("r10_missing", shared_vendor.id)
        body.pop("orgRole")
        resp = client.post(
            "/api/v3/users/create", json=body, headers=admin_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "orgRole" in resp.text or "org_role" in resp.text.lower()

    def test_invalid_orgrole_returns_422(
        self, client, admin_user, admin_headers, shared_vendor,
    ):
        body = _create_body(
            "r10_invalid", shared_vendor.id, orgRole="not_a_role",
        )
        resp = client.post(
            "/api/v3/users/create", json=body, headers=admin_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "orgrole" in resp.text.lower() or "org_role" in resp.text.lower()

    def test_valid_orgrole_creates_user(
        self, client, admin_user, admin_headers, shared_vendor,
    ):
        body = _create_body(
            "r10_valid", shared_vendor.id, orgRole="project_member",
        )
        resp = client.post(
            "/api/v3/users/create", json=body, headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# #4 — GET /users/check-login?login=…
# ---------------------------------------------------------------------------

class TestCheckLoginEndpoint:
    def test_returns_available_when_login_unused(
        self, client, admin_user, admin_headers,
    ):
        resp = client.get(
            "/api/v3/users/check-login?login=truly_unused_login",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body == {"login": "truly_unused_login", "available": True}

    def test_returns_taken_when_login_exists(
        self, client, admin_user, admin_headers, shared_vendor, db_session,
    ):
        existing = _make_user(db_session, "existing_user", shared_vendor.id)
        resp = client.get(
            f"/api/v3/users/check-login?login={existing.login}",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["available"] is False
        assert body["login"] == existing.login

    def test_requires_login_param(self, client, admin_user, admin_headers):
        resp = client.get(
            "/api/v3/users/check-login", headers=admin_headers,
        )
        assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# #6 / #13 — admin tier excluded from GET /users for non-admin caller
# ---------------------------------------------------------------------------

class TestExcludeAdminTierForNonAdmin:
    def test_oa_does_not_see_admin_users(
        self, client, admin_user, db_session, shared_vendor,
    ):
        """OA whose vendor coincidentally contains a PMIS-Admin user
        must NOT see that user in /users."""
        admin_in_vendor = _make_user(
            db_session, "admin_in_v", shared_vendor.id,
        )
        _grant_admin_legacy(db_session, admin_in_vendor)
        regular_in_vendor = _make_user(
            db_session, "regular_in_v", shared_vendor.id,
        )
        _, oa_headers = _make_oa(db_session, "oa_caller", shared_vendor.id)

        resp = client.get(
            "/api/v3/users?pageSize=50", headers=oa_headers,
        )
        assert resp.status_code == 200, resp.text
        logins = {
            u["login"]
            for u in resp.json()["data"]["_embedded"]["elements"]
        }
        assert regular_in_vendor.login in logins
        assert admin_in_vendor.login not in logins

    def test_oa_does_not_see_super_admin_users(
        self, client, admin_user, db_session, shared_vendor,
    ):
        """Same exclusion rule applies to super_admin tier — even via
        the doc-41 ``user_role_assignments`` row (not just legacy)."""
        sa_in_vendor = _make_user(
            db_session, "sa_in_v", shared_vendor.id,
        )
        _grant_super_admin_scoped(db_session, sa_in_vendor)
        _, oa_headers = _make_oa(db_session, "oa_caller_sa", shared_vendor.id)

        resp = client.get(
            "/api/v3/users?pageSize=50", headers=oa_headers,
        )
        logins = {
            u["login"]
            for u in resp.json()["data"]["_embedded"]["elements"]
        }
        assert sa_in_vendor.login not in logins

    def test_admin_caller_still_sees_admin_users(
        self, client, admin_user, admin_headers, db_session, shared_vendor,
    ):
        """Sanity — the exclusion only applies to non-admin callers.
        admin_user fixture itself is an admin tier user and must still
        appear in admin's listing."""
        resp = client.get(
            "/api/v3/users?pageSize=50", headers=admin_headers,
        )
        logins = {
            u["login"]
            for u in resp.json()["data"]["_embedded"]["elements"]
        }
        assert "admin" in logins
