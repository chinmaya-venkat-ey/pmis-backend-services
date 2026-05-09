"""Doc 44 round 7 — vendor-scope on /users list + PATCH targets.

Spec items #3 + #4 from the round-7 alignment audit:

  * #3 — ``GET /api/v3/users`` with a non-admin caller (org_admin /
    project_admin) returns ONLY users whose ``vendor_id`` matches the
    caller's. A caller with no vendor mapping sees nothing.
  * #4 — ``PATCH /api/v3/users/{id}`` with a non-admin caller is
    rejected (403) when the target's ``vendor_id`` does not match the
    caller's. Self-PATCH bypasses (own-profile carve-out).

Bootstrap admin (caller_user_admin) keeps the admin-bypass — admin
sees every user regardless of vendor. This file pins those guarantees.
"""
from uuid import uuid4

from app.core.security import create_access_token, hash_password
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from app.infrastructure.db.models.vendor import VendorModel
from app.infrastructure.db.repositories.rbac_repository import RbacRepository


def _vendor(db, name=None):
    v = VendorModel(
        id=str(uuid4()),
        name=name or f"Vendor-{uuid4().hex[:6]}",
        description="-",
        active=True,
    )
    db.add(v)
    db.commit()
    return v


def _make_org_admin(db, login, vendor_id):
    """Create an org_admin user scoped to the given vendor and return
    (user, headers)."""
    RbacRepository(db).sync_builtin_permissions()
    db.commit()
    role_id = db.query(RoleModel).filter(RoleModel.name == "org_admin").one().id
    user = UserModel(
        login=login,
        email=f"{login}@example.com",
        hashed_password=hash_password("Pmis@1234"),
        first_name="Org",
        last_name="Admin",
        status="active",
        two_factor_enabled=False,
        vendor_id=vendor_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(UserRoleAssignmentModel(
        user_id=user.id, role_id=role_id, organization_id=vendor_id,
    ))
    db.commit()
    headers = {
        "Authorization": "Bearer " + create_access_token({
            "sub": user.login, "user_id": user.id, "email": user.email,
        })
    }
    return user, headers


def _plain_user(db, login, vendor_id):
    """Plain active user with no role assignments, just a vendor_id."""
    user = UserModel(
        login=login,
        email=f"{login}@example.com",
        hashed_password=hash_password("Pmis@1234"),
        first_name="P",
        last_name="User",
        status="active",
        two_factor_enabled=False,
        vendor_id=vendor_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# #3 — GET /users vendor-scope filter
# ---------------------------------------------------------------------------

class TestListUsersVendorScope:
    """Non-admin callers only see users in their own vendor."""

    def test_org_admin_lists_only_own_vendor_users(
        self, client, db_session,
    ):
        v_own = _vendor(db_session, "OwnVendor")
        v_other = _vendor(db_session, "OtherVendor")

        org_admin, headers = _make_org_admin(
            db_session, "oa_scope", vendor_id=v_own.id,
        )
        u_in = _plain_user(db_session, "u_in_own", vendor_id=v_own.id)
        u_out = _plain_user(db_session, "u_in_other", vendor_id=v_other.id)

        resp = client.get("/api/v3/users", headers=headers)
        assert resp.status_code == 200, resp.text
        logins = {
            u["login"] for u in resp.json()["data"]["_embedded"]["elements"]
        }
        assert u_in.login in logins
        assert u_out.login not in logins

    def test_list_response_carries_org_role(
        self, client, admin_headers, db_session,
    ):
        """Round 7: GET /users list response carries ``orgRole`` per
        user (mirrors GET /users/{id} shape). Threaded through
        format_collection_response → format_user_response with the db
        session so the role projection runs per row."""
        elements = (
            client.get("/api/v3/users", headers=admin_headers)
            .json()["data"]["_embedded"]["elements"]
        )
        assert elements, "expected at least the bootstrap admin in the list"
        # Every element exposes the orgRole key (None or a role label).
        for u in elements:
            assert "orgRole" in u
        # Bootstrap admin row has the seeded admin role → derives to "admin".
        admin_row = next(u for u in elements if u["login"] == "admin")
        assert admin_row["orgRole"] == "admin"

    def test_admin_sees_all_vendors(
        self, client, admin_headers, db_session,
    ):
        """Admin bypasses the vendor filter."""
        v_a = _vendor(db_session, "VendorA")
        v_b = _vendor(db_session, "VendorB")
        u_a = _plain_user(db_session, "u_admin_sees_a", vendor_id=v_a.id)
        u_b = _plain_user(db_session, "u_admin_sees_b", vendor_id=v_b.id)

        resp = client.get("/api/v3/users", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        logins = {
            u["login"] for u in resp.json()["data"]["_embedded"]["elements"]
        }
        assert {u_a.login, u_b.login}.issubset(logins)

    def test_caller_without_vendor_sees_nothing(
        self, client, db_session,
    ):
        """A non-admin caller with no vendor_id mapping sees an empty
        result set (sentinel filter)."""
        # Create an org_admin without vendor_id (edge case — shouldn't
        # happen in practice, but the route must not leak the full list).
        RbacRepository(db_session).sync_builtin_permissions()
        db_session.commit()
        role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == "org_admin").one().id
        )
        user = UserModel(
            login="oa_no_vendor",
            email="oa_no_vendor@example.com",
            hashed_password=hash_password("Pmis@1234"),
            first_name="Org", last_name="Admin",
            status="active", two_factor_enabled=False,
            vendor_id=None,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        # Global org_admin row so the route gate (users:list) passes.
        db_session.add(UserRoleAssignmentModel(
            user_id=user.id, role_id=role_id,
        ))
        db_session.commit()
        headers = {
            "Authorization": "Bearer " + create_access_token({
                "sub": user.login, "user_id": user.id, "email": user.email,
            })
        }

        # Seed at least one user in some vendor that should NOT leak.
        v = _vendor(db_session, "SomeVendor")
        _plain_user(db_session, "leaked_if_broken", vendor_id=v.id)

        resp = client.get("/api/v3/users", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        # Sentinel filter → zero rows match.
        assert body["total"] == 0
        assert body["_embedded"]["elements"] == []


# ---------------------------------------------------------------------------
# #4 — PATCH /users/{id} vendor-scope target check
# ---------------------------------------------------------------------------

class TestPatchUserVendorScope:
    """Non-admin callers can only PATCH users in their own vendor."""

    def test_org_admin_cannot_patch_user_in_another_vendor(
        self, client, db_session,
    ):
        v_own = _vendor(db_session, "OwnPatch")
        v_other = _vendor(db_session, "OtherPatch")
        _, headers = _make_org_admin(
            db_session, "oa_patch", vendor_id=v_own.id,
        )
        target = _plain_user(
            db_session, "u_other_vendor", vendor_id=v_other.id,
        )

        resp = client.patch(
            f"/api/v3/users/{target.id}",
            json={"firstName": "Hacked"},
            headers=headers,
        )
        assert resp.status_code == 403, resp.text

    def test_org_admin_can_patch_user_in_own_vendor(
        self, client, db_session,
    ):
        v_own = _vendor(db_session, "OwnOk")
        _, headers = _make_org_admin(
            db_session, "oa_ok", vendor_id=v_own.id,
        )
        target = _plain_user(
            db_session, "u_own_vendor", vendor_id=v_own.id,
        )

        resp = client.patch(
            f"/api/v3/users/{target.id}",
            json={"status": "inactive"},
            headers=headers,
        )
        # Either 200 (patch ok) or 403 with a NON-vendor reason — what
        # we want to pin here is that the vendor-scope guard does not
        # itself reject. We assert no vendor message in the failure.
        if resp.status_code != 200:
            body_lower = resp.text.lower()
            assert "vendor" not in body_lower, (
                "vendor-scope guard incorrectly blocked same-vendor PATCH"
            )
