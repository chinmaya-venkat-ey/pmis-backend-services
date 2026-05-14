"""Doc 44 round 5 — user-CRUD perms locked to super_admin / admin.

Spec change: org_admin and project_admin lose ``users:create`` and
``users:update``; they keep ``users:read``, ``users:deactivate``,
``rbac:assign``, and the project_members:* set. The PATCH /users/{id}
route now accepts EITHER ``users:update`` (full edit) or
``users:deactivate`` (status field only); the service rejects any
non-status fields when the caller has only ``users:deactivate``.
"""
from uuid import uuid4

import pytest

from app.core.security import create_access_token, hash_password
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_permission import UserPermissionModel
from app.infrastructure.db.models.vendor import VendorModel
from app.infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from app.infrastructure.db.repositories.rbac_repository import RbacRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _vendor(db_session, name=None):
    v = VendorModel(
        id=str(uuid4()),
        name=name or f"Vendor-{uuid4().hex[:6]}",
        description="-",
        active=True,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


def _make_user_with_role(db_session, login, role_name, *, vendor_id=None):
    """Create a user and attach the given doc-41 scoped role globally
    (org_admin → org-scoped, project-tier roles → no project here so
    we use a global row for testing route gates)."""
    RbacRepository(db_session).sync_builtin_permissions()
    db_session.commit()
    role_id = (
        db_session.query(RoleModel).filter(RoleModel.name == role_name)
        .one().id
    )
    user = UserModel(
        login=login,
        email=f"{login}@example.com",
        hashed_password=hash_password("Pmis@1234"),
        first_name="T",
        last_name="User",
        status="active",
        two_factor_enabled=False,
        vendor_id=vendor_id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    if role_name == "org_admin":
        # Org-scoped row.
        db_session.add(UserRoleAssignmentModel(
            user_id=user.id, role_id=role_id, organization_id=vendor_id,
        ))
    else:
        # Global row (test only — production grants project-tier at project scope).
        db_session.add(UserRoleAssignmentModel(
            user_id=user.id, role_id=role_id,
        ))
    db_session.commit()
    return user, {
        "Authorization": "Bearer " + create_access_token({
            "sub": user.login, "user_id": user.id, "email": user.email,
        })
    }


# ---------------------------------------------------------------------------
# Seed-perm assertions: org_admin / project_admin no longer hold the
# CRUD codes; they hold users:deactivate instead.
# ---------------------------------------------------------------------------

class TestSeededPerms:
    def test_org_admin_does_not_hold_users_create_or_update(
        self, db_session, admin_user,
    ):
        # admin_user fixture triggers the seed loop.
        codes = set(
            RbacRepository(db_session).list_role_permissions(
                db_session.query(RoleModel).filter(
                    RoleModel.name == "org_admin"
                ).one().id
            )
        )
        assert "users:create" not in codes
        assert "users:update" not in codes
        assert "users:update_all" not in codes
        assert "users:deactivate" in codes
        assert "users:read" in codes

    def test_project_admin_does_not_hold_users_create_or_update(
        self, db_session, admin_user,
    ):
        codes = set(
            RbacRepository(db_session).list_role_permissions(
                db_session.query(RoleModel).filter(
                    RoleModel.name == "project_admin"
                ).one().id
            )
        )
        assert "users:create" not in codes
        assert "users:update" not in codes
        assert "users:deactivate" in codes
        assert "users:read" in codes


# ---------------------------------------------------------------------------
# PATCH /users/{id} gate behaviour.
# ---------------------------------------------------------------------------

class TestPatchUserGate:
    def test_org_admin_can_deactivate_user(
        self, client, admin_user, db_session,
    ):
        """Caller with USERS_DEACTIVATE only — body limited to status."""
        vendor = _vendor(db_session)
        oa, oa_headers = _make_user_with_role(
            db_session, f"oa_{uuid4().hex[:6]}", "org_admin",
            vendor_id=vendor.id,
        )
        # A target user to deactivate.
        target = UserModel(
            login=f"tgt_{uuid4().hex[:6]}",
            email=f"tgt_{uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("Pmis@1234"),
            first_name="Target", last_name="User",
            status="active", two_factor_enabled=False,
            vendor_id=vendor.id,
        )
        db_session.add(target)
        db_session.commit()
        db_session.refresh(target)

        resp = client.patch(
            f"/api/v3/users/{target.id}",
            json={"status": "inactive"},
            headers=oa_headers,
        )
        assert resp.status_code == 200, resp.text

    def test_org_admin_cannot_edit_non_status_fields(
        self, client, admin_user, db_session,
    ):
        """Caller with only USERS_DEACTIVATE → patching firstName etc.
        is forbidden (400+ status; the route surfaces 403 with a
        message naming the disallowed fields)."""
        vendor = _vendor(db_session)
        oa, oa_headers = _make_user_with_role(
            db_session, f"oa2_{uuid4().hex[:6]}", "org_admin",
            vendor_id=vendor.id,
        )
        target = UserModel(
            login=f"tgt_{uuid4().hex[:6]}",
            email=f"tgt_{uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("Pmis@1234"),
            first_name="Target", last_name="User",
            status="active", two_factor_enabled=False,
            vendor_id=vendor.id,
        )
        db_session.add(target)
        db_session.commit()
        db_session.refresh(target)

        resp = client.patch(
            f"/api/v3/users/{target.id}",
            json={"fullName": "Hacker Person"},
            headers=oa_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "users:deactivate" in resp.json()["error"]["message"].lower() \
            or "deactivate" in resp.json()["error"]["message"].lower()

    def test_admin_can_edit_any_field(
        self, client, admin_user, admin_headers, member_user,
    ):
        """admin holds USERS_UPDATE, so the field-restriction doesn't apply."""
        resp = client.patch(
            f"/api/v3/users/{member_user.id}",
            json={"fullName": "Edited Person"},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# POST /users/create gate behaviour — org_admin / project_admin no
# longer hold USERS_CREATE so they're rejected at the route gate.
# ---------------------------------------------------------------------------

class TestCreateUserGateRound5:
    def test_org_admin_cannot_create_user(
        self, client, admin_user, db_session,
    ):
        vendor = _vendor(db_session)
        _, oa_headers = _make_user_with_role(
            db_session, f"oa_create_{uuid4().hex[:6]}", "org_admin",
            vendor_id=vendor.id,
        )
        body = {
            "login": f"new_{uuid4().hex[:6]}",
            "email": f"new_{uuid4().hex[:6]}@example.com",
            "password": "Pmis@1234",
            "firstName": "New", "lastName": "User",
            "phone_number": "9999999999",
            "vendor_id": vendor.id,
            "division": "tmd1",
            "project_ids": [],
        }
        resp = client.post("/api/v3/users/create", json=body, headers=oa_headers)
        assert resp.status_code == 403, resp.text
