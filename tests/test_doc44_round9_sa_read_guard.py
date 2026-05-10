"""Doc 44 round 9 — F1 read-side hierarchy guard on GET /users/{id}.

Bug #5 from the round-9 tester report: PMIS Admin (legacy ``admin``
tier) was able to fetch the super_admin user's profile via
``GET /api/v3/users/{sa_id}``. Round 7 added the F1 hierarchy gate
to PATCH / password / DELETE on `users.routes` via
``can_caller_modify_user``, but the read-side was missed.

Round 9 closes the gap in ``UserController.get`` — only super_admin
may read another super_admin's profile. Self-fetch always works.
"""
from uuid import uuid4

from app.core.security import create_access_token, hash_password
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)


def _make_user(db_session, login):
    u = UserModel(
        login=f"{login}-{uuid4().hex[:6]}",
        email=f"{login}-{uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pmis@1234"),
        first_name="T", last_name="User",
        status="active", two_factor_enabled=False,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _grant_super_admin(db_session, user):
    role_id = (
        db_session.query(RoleModel)
        .filter(RoleModel.name == "super_admin")
        .one().id
    )
    db_session.add(UserRoleAssignmentModel(
        user_id=user.id, role_id=role_id,
    ))
    db_session.commit()


def _headers(user):
    return {
        "Authorization": "Bearer " + create_access_token({
            "sub": user.login, "user_id": user.id, "email": user.email,
        })
    }


class TestSuperAdminReadGuard:
    def test_admin_blocked_from_reading_super_admin(
        self, client, admin_user, admin_headers, db_session,
    ):
        """admin (PMIS Admin tier) → super_admin GET → 403."""
        sa = _make_user(db_session, "sa-target")
        _grant_super_admin(db_session, sa)

        resp = client.get(f"/api/v3/users/{sa.id}", headers=admin_headers)
        assert resp.status_code == 403, resp.text
        assert "super_admin" in resp.text.lower()

    def test_super_admin_can_read_super_admin(
        self, client, admin_user, admin_headers, db_session,
    ):
        """SA → SA read remains allowed (the existing G2/G3 destructive
        peer-takeover guards apply to PATCH/password/DELETE, not GET)."""
        # Promote the bootstrap admin to super_admin so the call is SA → SA.
        _grant_super_admin(db_session, admin_user)
        target = _make_user(db_session, "sa-target-2")
        _grant_super_admin(db_session, target)

        resp = client.get(f"/api/v3/users/{target.id}", headers=admin_headers)
        assert resp.status_code == 200, resp.text

    def test_super_admin_self_read_works(
        self, client, admin_user, admin_headers, db_session,
    ):
        """Self-fetch always allowed (caller_id == target_id bypasses
        the hierarchy gate)."""
        _grant_super_admin(db_session, admin_user)
        resp = client.get(
            f"/api/v3/users/{admin_user.id}", headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text

    def test_non_super_admin_target_unaffected(
        self, client, admin_user, admin_headers, db_session,
    ):
        """admin reading a regular (non-SA) user still works."""
        regular = _make_user(db_session, "regular")
        resp = client.get(
            f"/api/v3/users/{regular.id}", headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
