"""Mirror of monolith doc-44 round 9 + doc-46 rounds 10b/10c/11b/11c/11d/12
— the eight items that depend on the doc-41 scoped-RBAC backport now
landed on project-service.

  * Round 9   — PATCH /vendors tier-aware allowlist
  * Round 10b — PATCH /vendors no-op tolerance for OA round-trip
  * Round 10c — vendor user_assignments hydrate with login + name
  * Round 11b — GET /projects/{id}/assignable-users
  * Round 11c — bind newly-granted users to vendor on PATCH
  * Round 11d — always emit PA / PM buckets in user_assignments response
  * Round 12  — PA-scope filter on GET /vendors/{id}
  * Round 11b hotfix — exclude admin / super_admin from assignable-users

The scoped-tier roles (``org_admin`` / ``project_admin`` / ``project_member``
/ ``division_member``) are seeded by user-service in production; tests
insert minimal role rows directly into the shared in-memory DB.
"""
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.project_vendor import ProjectVendorModel
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_permission import UserPermissionModel
from app.infrastructure.db.models.user_role import UserRoleModel
from app.infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from app.infrastructure.db.models.vendor import VendorModel


# ---------------------------------------------------------------------------
# Scoped-RBAC test seed helpers
# ---------------------------------------------------------------------------

_SCOPED_TIER_ROLES = (
    "super_admin", "org_admin", "project_admin",
    "project_member", "division_member",
)


def _seed_scoped_tier_roles(db):
    """Insert the 5 scoped-tier role rows into the shared DB so the
    name-lookup queries in vendor PATCH gate + assignable-users
    endpoint can resolve them. In production user-service does this
    at boot; tests bootstrap it themselves."""
    from app.infrastructure.db.repositories.rbac_repository import RbacRepository
    RbacRepository(db).sync_builtin_permissions()
    for name in _SCOPED_TIER_ROLES:
        if db.query(RoleModel).filter(RoleModel.name == name).first() is None:
            db.add(RoleModel(name=name, description=f"Scoped tier role: {name}"))
    db.commit()


def _make_user(db, *, login, email=None, vendor_id=None):
    uid = str(uuid4())
    db.add(UserModel(
        id=uid,
        login=login,
        email=email or f"{login}@x.example.com",
        first_name=login.title(),
        last_name="Tester",
        hashed_password="not-used",
        status="active",
        vendor_id=vendor_id,
    ))
    db.commit()
    return uid


def _grant_perm(db, *, user_id, permission_code):
    db.add(UserPermissionModel(user_id=user_id, permission_code=permission_code))
    db.commit()


def _assign_legacy_role(db, *, user_id, role_name):
    role = db.query(RoleModel).filter(RoleModel.name == role_name).first()
    assert role is not None, f"role {role_name} not seeded"
    db.add(UserRoleModel(user_id=user_id, role_id=role.id))
    db.commit()


def _add_scoped_assignment(
    db, *, user_id, role_name, organization_id=None, project_id=None,
):
    role = db.query(RoleModel).filter(RoleModel.name == role_name).first()
    assert role is not None, f"role {role_name} not seeded"
    db.add(UserRoleAssignmentModel(
        user_id=user_id,
        role_id=role.id,
        organization_id=organization_id,
        project_id=project_id,
    ))
    db.commit()


def _token(*, user_id, login="testuser", email=None):
    return create_access_token({
        "sub": login,
        "user_id": user_id,
        "email": email or f"{login}@x.example.com",
    })


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _make_vendor(db, *, name=None, email=None, phone="+919999999999"):
    v = VendorModel(
        id=str(uuid4()),
        vendor_code=f"VN-{uuid4().hex[:8]}",
        name=name or f"Vendor-{uuid4().hex[:6]}",
        active=True,
        email=email,
        phone_number=phone,
    )
    db.add(v)
    db.commit()
    return v


def _make_project(db, *, name=None, owner="tmd1", status="published"):
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"UIDAI-PR{uuid4().hex[:10]}",
        name=name or f"Project-{uuid4().hex[:6]}",
        status=status,
        owner=owner,
    )
    db.add(p)
    db.commit()
    return p


def _attach_vendor_project(db, *, vendor_id, project_id):
    db.add(ProjectVendorModel(vendor_id=vendor_id, project_id=project_id))
    db.commit()


# ---------------------------------------------------------------------------
# Fixtures: a vendor + org_admin + project_admin + project_member, all wired.
# ---------------------------------------------------------------------------

@pytest.fixture
def scoped_world(db_session):
    """Seed a complete cross-link world for the scoped-RBAC tests:

      * Two vendors (V1, V2).
      * Two projects under V1 (P1, P2).
      * One project under V2 (P3).
      * OA user — org_admin on V1.
      * PA user — project_admin on P1 only.
      * Member user — no scoped assignment.
      * Admin user — legacy ``admin`` role.

    OA and PA also hold the ``rbac:assign`` direct permission so the
    PATCH /vendors body-shape gate path is exercised.
    """
    _seed_scoped_tier_roles(db_session)

    v1 = _make_vendor(db_session, name="V1", email="v1@x.example.com")
    v2 = _make_vendor(db_session, name="V2", email="v2@x.example.com")
    p1 = _make_project(db_session, name="P1")
    p2 = _make_project(db_session, name="P2")
    p3 = _make_project(db_session, name="P3")
    _attach_vendor_project(db_session, vendor_id=v1.id, project_id=p1.id)
    _attach_vendor_project(db_session, vendor_id=v1.id, project_id=p2.id)
    _attach_vendor_project(db_session, vendor_id=v2.id, project_id=p3.id)

    oa_id = _make_user(db_session, login="oa_user", vendor_id=v1.id)
    pa_id = _make_user(db_session, login="pa_user", vendor_id=v1.id)
    pm_id = _make_user(db_session, login="pm_user", vendor_id=v1.id)
    admin_id = _make_user(db_session, login="admin_full", vendor_id=v1.id)
    member_id = _make_user(db_session, login="plain_member", vendor_id=v1.id)

    for uid in (oa_id, pa_id, pm_id):
        # Minimal read perms each tier needs to traverse the FE flows
        # under test. ``rbac:assign`` is what gates vendor PATCH on the
        # OA/PA tier; ``vendors:read`` and ``project_members:read`` are
        # what gate the GET endpoints they hit.
        _grant_perm(db_session, user_id=uid, permission_code="vendors:read")
        _grant_perm(db_session, user_id=uid, permission_code="project_members:read")
    _grant_perm(db_session, user_id=oa_id, permission_code="rbac:assign")
    _grant_perm(db_session, user_id=pa_id, permission_code="rbac:assign")
    _add_scoped_assignment(
        db_session, user_id=oa_id, role_name="org_admin",
        organization_id=v1.id,
    )
    _add_scoped_assignment(
        db_session, user_id=pa_id, role_name="project_admin",
        project_id=p1.id,
    )
    _assign_legacy_role(db_session, user_id=admin_id, role_name="admin")
    _assign_legacy_role(db_session, user_id=member_id, role_name="member")

    return {
        "v1": v1, "v2": v2,
        "p1": p1, "p2": p2, "p3": p3,
        "oa_id": oa_id, "pa_id": pa_id, "pm_id": pm_id,
        "admin_id": admin_id, "member_id": member_id,
        "oa_headers": _headers(_token(user_id=oa_id, login="oa_user")),
        "pa_headers": _headers(_token(user_id=pa_id, login="pa_user")),
        "pm_headers": _headers(_token(user_id=pm_id, login="pm_user")),
        "admin_headers": _headers(_token(user_id=admin_id, login="admin_full")),
        "member_headers": _headers(_token(user_id=member_id, login="plain_member")),
    }


# ---------------------------------------------------------------------------
# Doc 44 round 9 — PATCH /vendors tier-aware allowlist
# ---------------------------------------------------------------------------

class TestPATCHVendorsTierAllowlist:
    def test_admin_can_edit_name(self, client, scoped_world):
        v1 = scoped_world["v1"]
        r = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["admin_headers"],
            json={"name": "V1-renamed"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["name"] == "V1-renamed"

    def test_oa_blocked_editing_name(self, client, scoped_world):
        v1 = scoped_world["v1"]
        r = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["oa_headers"],
            json={"name": "V1-renamed"},
        )
        assert r.status_code == 403, r.text
        assert "name" in r.text.lower()

    def test_oa_can_edit_email_on_own_vendor(self, client, scoped_world):
        v1 = scoped_world["v1"]
        r = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["oa_headers"],
            json={"email": "new-oa@x.example.com"},
        )
        assert r.status_code == 200, r.text

    def test_oa_blocked_on_other_vendor(self, client, scoped_world):
        v2 = scoped_world["v2"]
        r = client.patch(
            f"/api/v3/vendors/{v2.id}",
            headers=scoped_world["oa_headers"],
            json={"email": "x@x.example.com"},
        )
        assert r.status_code == 403, r.text

    def test_pa_can_only_edit_user_assignments(self, client, scoped_world):
        v1 = scoped_world["v1"]
        # PA editing email → 403.
        r1 = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["pa_headers"],
            json={"email": "fail@x.example.com"},
        )
        assert r1.status_code == 403, r1.text
        # PA editing user_assignments only → 200.
        r2 = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["pa_headers"],
            json={"user_assignments": []},
        )
        assert r2.status_code == 200, r2.text

    def test_plain_member_rejected_entirely(self, client, scoped_world):
        v1 = scoped_world["v1"]
        r = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["member_headers"],
            json={"email": "x@x.example.com"},
        )
        # Member doesn't hold vendors:manage OR rbac:assign.
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Doc 46 round 10b — PATCH /vendors no-op tolerance for OA round-trip
# ---------------------------------------------------------------------------

class TestPATCHVendorsNoOpTolerance:
    def test_oa_full_round_trip_with_unchanged_fields_succeeds(
        self, client, scoped_world,
    ):
        """OA sends the full vendor body back — including ``name`` /
        ``description`` / ``active`` that they can't normally edit.
        Because none of them are actually changing, the gate should
        treat them as no-ops and pass."""
        v1 = scoped_world["v1"]
        # First GET so we know the current values.
        cur = client.get(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["admin_headers"],
        ).json()["data"]
        r = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["oa_headers"],
            json={
                "name": cur["name"],
                "description": cur.get("description") or "",
                "active": cur["active"],
                "email": "round-trip@x.example.com",
            },
        )
        assert r.status_code == 200, r.text

    def test_oa_round_trip_with_changed_name_rejected(
        self, client, scoped_world,
    ):
        v1 = scoped_world["v1"]
        r = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["oa_headers"],
            json={"name": "V1-NEW-NAME", "email": "ok@x.example.com"},
        )
        assert r.status_code == 403, r.text
        assert "name" in r.text.lower()


# ---------------------------------------------------------------------------
# Doc 44 round 6 + round 10c + round 11d — user_assignments matrix
# ---------------------------------------------------------------------------

class TestVendorUserAssignmentsMatrix:
    def test_get_vendor_emits_always_pa_pm_buckets(
        self, client, scoped_world,
    ):
        v1 = scoped_world["v1"]
        r = client.get(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["admin_headers"],
        )
        assert r.status_code == 200, r.text
        ua = r.json()["data"]["user_assignments"]
        # Round 11d — every (project, role) combo for PA + PM emitted
        # even when empty. V1 has P1 and P2 → 4 entries.
        keys = sorted((e["project_id"], e["role"]) for e in ua)
        p1 = scoped_world["p1"].id
        p2 = scoped_world["p2"].id
        assert (p1, "Project Admin") in keys
        assert (p1, "Project Member") in keys
        assert (p2, "Project Admin") in keys
        assert (p2, "Project Member") in keys

    def test_patch_user_assignments_grants_and_binds_vendor(
        self, client, scoped_world, db_session,
    ):
        v1 = scoped_world["v1"]
        p1 = scoped_world["p1"]
        # Fresh user with no vendor binding yet.
        new_uid = _make_user(db_session, login="new_pm_user")
        before = (
            db_session.query(UserModel.vendor_id)
            .filter(UserModel.id == new_uid)
            .scalar()
        )
        assert before is None

        r = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["admin_headers"],
            json={
                "user_assignments": [
                    {
                        "project_id": p1.id,
                        "role": "Project Member",
                        "user_ids": [new_uid],
                    },
                ],
            },
        )
        assert r.status_code == 200, r.text

        # Round 11c — new grant should also bind users.vendor_id.
        db_session.expire_all()
        after = (
            db_session.query(UserModel.vendor_id)
            .filter(UserModel.id == new_uid)
            .scalar()
        )
        assert after == v1.id

        # Round 10c — response hydrates user_assignments with login+name.
        ua = r.json()["data"]["user_assignments"]
        target_row = next(
            (e for e in ua if e["project_id"] == p1.id and e["role"] == "Project Member"),
            None,
        )
        assert target_row is not None
        assert target_row["users"], "users[] should not be empty"
        assert target_row["users"][0]["login"] == "new_pm_user"

    def test_patch_user_assignments_revokes_dropped_users(
        self, client, scoped_world, db_session,
    ):
        v1 = scoped_world["v1"]
        p1 = scoped_world["p1"]
        u_keep = _make_user(db_session, login="keep_user")
        u_drop = _make_user(db_session, login="drop_user")
        # Grant both first.
        r1 = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["admin_headers"],
            json={"user_assignments": [{
                "project_id": p1.id, "role": "Project Member",
                "user_ids": [u_keep, u_drop],
            }]},
        )
        assert r1.status_code == 200
        # Re-send with only u_keep — u_drop must be revoked.
        r2 = client.patch(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["admin_headers"],
            json={"user_assignments": [{
                "project_id": p1.id, "role": "Project Member",
                "user_ids": [u_keep],
            }]},
        )
        assert r2.status_code == 200
        db_session.expire_all()
        remaining = {
            uid for (uid,) in (
                db_session.query(UserRoleAssignmentModel.user_id)
                .filter(UserRoleAssignmentModel.project_id == p1.id)
                .all()
            )
        }
        assert u_keep in remaining
        assert u_drop not in remaining
        # PA user was assigned in scoped_world too — leave that intact.
        assert scoped_world["pa_id"] in remaining


# ---------------------------------------------------------------------------
# Doc 46 round 12 — PA-scope filter on GET /vendors/{id}
# ---------------------------------------------------------------------------

class TestGETVendorPAScope:
    def test_admin_sees_all_projects(self, client, scoped_world):
        v1 = scoped_world["v1"]
        r = client.get(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["admin_headers"],
        )
        names = sorted(p["name"] for p in r.json()["data"]["projects"])
        assert names == ["P1", "P2"]

    def test_oa_sees_all_projects_in_vendor(self, client, scoped_world):
        v1 = scoped_world["v1"]
        r = client.get(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["oa_headers"],
        )
        names = sorted(p["name"] for p in r.json()["data"]["projects"])
        assert names == ["P1", "P2"]

    def test_pa_sees_only_assigned_project(self, client, scoped_world):
        """PA is project_admin on P1 only. GET /vendors/V1 should
        narrow ``projects`` and ``user_assignments`` to P1 alone."""
        v1 = scoped_world["v1"]
        r = client.get(
            f"/api/v3/vendors/{v1.id}",
            headers=scoped_world["pa_headers"],
        )
        assert r.status_code == 200, r.text
        names = [p["name"] for p in r.json()["data"]["projects"]]
        assert names == ["P1"]
        ua_pids = {e["project_id"] for e in r.json()["data"]["user_assignments"]}
        assert ua_pids == {scoped_world["p1"].id}


# ---------------------------------------------------------------------------
# Doc 46 round 11b + hotfix — GET /projects/{id}/assignable-users
# ---------------------------------------------------------------------------

class TestAssignableUsers:
    def test_returns_project_scoped_users(
        self, client, scoped_world,
    ):
        p1 = scoped_world["p1"]
        r = client.get(
            f"/api/v3/projects/{p1.id}/assignable-users",
            headers=scoped_world["admin_headers"],
        )
        assert r.status_code == 200, r.text
        logins = [u["login"] for u in r.json()["data"]["users"]]
        # PA is assigned to P1 → must appear.
        assert "pa_user" in logins
        # OA is on V1 (owner of P1) → must appear.
        assert "oa_user" in logins

    def test_admin_tier_excluded(
        self, client, scoped_world, db_session,
    ):
        """Hotfix: a user holding admin AND a project-tier role on the
        same project must NOT appear in assignable-users."""
        p1 = scoped_world["p1"]
        # Grant the admin user a project_admin assignment on P1 too.
        _add_scoped_assignment(
            db_session, user_id=scoped_world["admin_id"],
            role_name="project_admin", project_id=p1.id,
        )
        r = client.get(
            f"/api/v3/projects/{p1.id}/assignable-users",
            headers=scoped_world["admin_headers"],
        )
        assert r.status_code == 200, r.text
        logins = [u["login"] for u in r.json()["data"]["users"]]
        assert "admin_full" not in logins

    def test_404_on_unknown_project(self, client, scoped_world):
        r = client.get(
            "/api/v3/projects/no-such-id/assignable-users",
            headers=scoped_world["admin_headers"],
        )
        assert r.status_code == 404, r.text

    def test_de_dup_when_user_holds_both_project_and_org_roles(
        self, client, scoped_world, db_session,
    ):
        """A user holding both project-tier AND org_admin should
        appear once."""
        p1 = scoped_world["p1"]
        # Make OA also a PA on P1.
        _add_scoped_assignment(
            db_session, user_id=scoped_world["oa_id"],
            role_name="project_admin", project_id=p1.id,
        )
        r = client.get(
            f"/api/v3/projects/{p1.id}/assignable-users",
            headers=scoped_world["admin_headers"],
        )
        logins = [u["login"] for u in r.json()["data"]["users"]]
        assert logins.count("oa_user") == 1
