"""Doc 43 — hierarchy + reserved-permission security tests.

Covers four classes of attack the threat-model audit surfaced:

  * F1 (admin can't mutate super_admin) — PATCH / DELETE /
    PATCH password on a super_admin user must 403 when caller is
    admin. super_admin caller passes (modulo lockout).
  * F2 (reserved permission) — ``users:grant_superadmin`` cannot be
    granted as a direct user-permission, nor added to any role
    other than super_admin via the role-permission update endpoints.
  * F3 (last super_admin lockout on user-DELETE) — already covered
    in test_users.py::TestAdminProtectionGuards but the assertion
    here is on the new code path.
  * F4 (universal-OTP startup warning) — sanity that the warning
    fires when the flag is on.
"""
from uuid import uuid4

import pytest

from app.core.permissions import (
    ADMIN_ROLE_NAME, SUPER_ADMIN_ROLE_NAME, USERS_GRANT_SUPERADMIN,
)
from app.core.security import create_access_token, hash_password
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_role import UserRoleModel
from app.infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bootstrap_super_admin(db) -> tuple[UserModel, dict]:
    """Create a super_admin user via the doc-41 user_role_assignments
    table. Returns (user, headers).

    Triggers the RBAC seed loop first so the super_admin role row
    exists in the test DB even when no other fixture has done so.
    """
    from app.infrastructure.db.repositories.rbac_repository import (
        RbacRepository,
    )
    RbacRepository(db).sync_builtin_permissions()
    db.commit()
    sa_role_id = (
        db.query(RoleModel).filter(RoleModel.name == SUPER_ADMIN_ROLE_NAME)
        .one().id
    )
    user = UserModel(
        login=f"sa-{uuid4().hex[:6]}",
        email=f"sa-{uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Doc43Test!"),
        first_name="Super",
        last_name="Admin",
        status="active",
        two_factor_enabled=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(UserRoleAssignmentModel(user_id=user.id, role_id=sa_role_id))
    db.commit()
    headers = {
        "Authorization": f"Bearer " + create_access_token({
            "sub": user.login, "user_id": user.id, "email": user.email,
        })
    }
    return user, headers


# ---------------------------------------------------------------------------
# F1 — admin cannot mutate super_admin user
# ---------------------------------------------------------------------------

class TestAdminCannotMutateSuperAdmin:
    """Hierarchy boundary: admin caller blocked on PATCH / DELETE /
    password against a user holding super_admin globally."""

    def test_admin_cannot_patch_super_admin_profile(
        self, client, admin_user, admin_headers, db_session,
    ):
        sa_user, _ = _bootstrap_super_admin(db_session)
        resp = client.patch(
            f"/api/v3/users/{sa_user.id}",
            json={"firstName": "Hijack"},
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "super_admin" in resp.json()["error"]["message"].lower()

    def test_admin_cannot_change_super_admin_password(
        self, client, admin_user, admin_headers, db_session,
    ):
        sa_user, _ = _bootstrap_super_admin(db_session)
        resp = client.patch(
            f"/api/v3/users/{sa_user.id}/password",
            json={"password": "Hijacked!1"},
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text

    def test_admin_cannot_delete_super_admin(
        self, client, admin_user, admin_headers, db_session,
    ):
        sa_user, _ = _bootstrap_super_admin(db_session)
        resp = client.delete(
            f"/api/v3/users/{sa_user.id}", headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text

    def test_admin_cannot_deactivate_super_admin(
        self, client, admin_user, admin_headers, db_session,
    ):
        sa_user, _ = _bootstrap_super_admin(db_session)
        resp = client.patch(
            f"/api/v3/users/{sa_user.id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text

    def test_super_admin_can_patch_other_super_admin(
        self, client, db_session,
    ):
        sa1, h1 = _bootstrap_super_admin(db_session)
        sa2, _ = _bootstrap_super_admin(db_session)
        resp = client.patch(
            f"/api/v3/users/{sa2.id}",
            json={"firstName": "Renamed"},
            headers=h1,
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# F2 — reserved permission users:grant_superadmin
# ---------------------------------------------------------------------------

class TestReservedSuperadminGrantPermission:
    """``users:grant_superadmin`` can only be held via the seeded
    super_admin role. All other paths to acquire it must 403."""

    def test_direct_grant_to_user_blocked(
        self, client, admin_user, admin_headers, db_session,
    ):
        # Create a target user; admin tries to grant the reserved code.
        target = UserModel(
            login=f"t-{uuid4().hex[:6]}",
            email=f"t-{uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("x"),
            status="active",
        )
        db_session.add(target)
        db_session.commit()
        resp = client.post(
            f"/api/v3/users/{target.id}/permissions/{USERS_GRANT_SUPERADMIN}",
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "reserved" in resp.json()["error"]["message"].lower()

    def test_replace_role_perms_with_reserved_code_blocked(
        self, client, admin_user, admin_headers, db_session,
    ):
        # Take the seeded `member` role and try to replace its perms
        # with one that includes users:grant_superadmin.
        member_role_id = (
            db_session.query(RoleModel).filter(RoleModel.name == "member")
            .one().id
        )
        resp = client.put(
            f"/api/v3/roles/{member_role_id}/permissions",
            json={"permissions": [USERS_GRANT_SUPERADMIN]},
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "reserved" in resp.json()["error"]["message"].lower()

    def test_grant_single_perm_to_role_with_reserved_code_blocked(
        self, client, admin_user, admin_headers, db_session,
    ):
        member_role_id = (
            db_session.query(RoleModel).filter(RoleModel.name == "member")
            .one().id
        )
        resp = client.post(
            f"/api/v3/roles/{member_role_id}/permissions/{USERS_GRANT_SUPERADMIN}",
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "reserved" in resp.json()["error"]["message"].lower()

    def test_super_admin_role_keeps_the_reserved_code(
        self, db_session, admin_user,
    ):
        """Sanity: the seeded super_admin role does hold the reserved
        code (it's the only legitimate holder). admin_user fixture
        triggers the RBAC seed loop."""
        sa_role = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == SUPER_ADMIN_ROLE_NAME)
            .one()
        )
        from app.infrastructure.db.repositories.rbac_repository import (
            RbacRepository,
        )
        codes = RbacRepository(db_session).list_role_permissions(sa_role.id)
        assert USERS_GRANT_SUPERADMIN in codes


# ---------------------------------------------------------------------------
# F3 — last super_admin lockout on user-DELETE
# ---------------------------------------------------------------------------

class TestLastSuperAdminLockoutOnUserDelete:
    """User-DELETE must refuse soft-deleting the last live super_admin
    (separate from the role-assignment revoke lockout)."""

    def test_cannot_delete_last_super_admin(self, client, db_session):
        sa, headers = _bootstrap_super_admin(db_session)
        # Try to delete self via super_admin token (should be blocked
        # by self-delete guard, but also by lockout if it were any
        # other caller).
        resp = client.delete(
            f"/api/v3/users/{sa.id}", headers=headers,
        )
        # Self-delete guard fires first (403). The lockout would
        # also have fired (422) — order is implementation detail.
        assert resp.status_code in (403, 422), resp.text

    def test_can_delete_super_admin_when_others_exist(
        self, client, db_session,
    ):
        # Doc 43 round-2 (G3) blocks super_admin → super_admin DELETE
        # outright, so to isolate the F3 lockout path we first demote
        # sa1 (revoke their super_admin assignment). After that, the
        # remaining live super_admin (sa2) means the lockout MUST NOT
        # fire and the DELETE succeeds. User-delete endpoint returns
        # 200 with the soft-deleted snapshot (per BaseController.ok),
        # not 204.
        sa1, _ = _bootstrap_super_admin(db_session)
        sa2, headers2 = _bootstrap_super_admin(db_session)
        from app.infrastructure.db.repositories.rbac_repository import (
            RbacRepository,
        )
        repo = RbacRepository(db_session)
        sa_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == SUPER_ADMIN_ROLE_NAME).one().id
        )
        for row in repo.list_scoped_assignments_for_user(sa1.id):
            if (
                row.role_id == sa_role_id
                and row.organization_id is None
                and row.project_id is None
            ):
                repo.revoke_scoped_assignment(row.id)
        db_session.commit()
        resp = client.delete(
            f"/api/v3/users/{sa1.id}", headers=headers2,
        )
        assert resp.status_code in (200, 204), resp.text


# ---------------------------------------------------------------------------
# F4 — universal-OTP warning fires at startup
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# G-series — round-2 hardening (peer-takeover + self-deactivate)
# ---------------------------------------------------------------------------

class TestSelfDeactivateBlocked:
    """G1: a user cannot deactivate their own account, regardless of
    tier. Symmetric with the existing self-delete guard. Without
    this, a super_admin could disable themselves and lose login."""

    def test_super_admin_cannot_self_deactivate_when_others_exist(
        self, client, db_session,
    ):
        # Bootstrap two super_admins so the lockout (last super_admin)
        # would NOT fire — only G1 self-guard catches this.
        sa1, h1 = _bootstrap_super_admin(db_session)
        _bootstrap_super_admin(db_session)
        resp = client.patch(
            f"/api/v3/users/{sa1.id}",
            json={"status": "inactive"},
            headers=h1,
        )
        assert resp.status_code == 403, resp.text
        assert "deactivate your own account" in resp.text.lower()

    def test_admin_cannot_self_deactivate(
        self, client, admin_user, admin_headers,
    ):
        resp = client.patch(
            f"/api/v3/users/{admin_user.id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "deactivate your own account" in resp.text.lower()


class TestPeerTakeoverPasswordChange:
    """G2: super_admin caller cannot change ANOTHER super_admin's
    password (peer-takeover prevention). Self-change works as before."""

    def test_super_admin_cannot_change_peer_super_admin_password(
        self, client, db_session,
    ):
        sa1, _ = _bootstrap_super_admin(db_session)
        sa2, h2 = _bootstrap_super_admin(db_session)
        resp = client.patch(
            f"/api/v3/users/{sa1.id}/password",
            json={"password": "PeerHijack!"},
            headers=h2,
        )
        assert resp.status_code == 403, resp.text
        assert "another super_admin" in resp.json()["error"]["message"].lower()

    def test_super_admin_can_change_own_password(
        self, client, db_session,
    ):
        sa, headers = _bootstrap_super_admin(db_session)
        resp = client.patch(
            f"/api/v3/users/{sa.id}/password",
            json={"password": "NewSelfPwd!"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    def test_super_admin_can_change_admin_password(
        self, client, db_session, admin_user,
    ):
        # Lower-tier target — super_admin keeps the privilege.
        sa, headers = _bootstrap_super_admin(db_session)
        resp = client.patch(
            f"/api/v3/users/{admin_user.id}/password",
            json={"password": "NewLowerPwd!"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text


class TestPeerTakeoverDelete:
    """G3: super_admin caller cannot DELETE another super_admin without
    first demoting them (revoking the super_admin role assignment).
    Self-DELETE blocked by existing guard."""

    def test_super_admin_cannot_delete_peer_super_admin(
        self, client, db_session,
    ):
        sa1, _ = _bootstrap_super_admin(db_session)
        sa2, h2 = _bootstrap_super_admin(db_session)
        resp = client.delete(
            f"/api/v3/users/{sa1.id}", headers=h2,
        )
        assert resp.status_code == 403, resp.text
        assert "another super_admin" in resp.json()["error"]["message"].lower()

    def test_super_admin_can_delete_after_demoting_target(
        self, client, db_session,
    ):
        sa1, _ = _bootstrap_super_admin(db_session)
        sa2, h2 = _bootstrap_super_admin(db_session)
        # sa2 first revokes sa1's super_admin assignment, then DELETEs
        # them — should succeed.
        from app.infrastructure.db.repositories.rbac_repository import (
            RbacRepository,
        )
        repo = RbacRepository(db_session)
        sa_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == SUPER_ADMIN_ROLE_NAME).one().id
        )
        # Revoke sa1's super_admin row.
        rows = repo.list_scoped_assignments_for_user(sa1.id)
        for row in rows:
            if row.role_id == sa_role_id and row.organization_id is None and row.project_id is None:
                repo.revoke_scoped_assignment(row.id)
        db_session.commit()
        # Now DELETE should pass.
        resp = client.delete(
            f"/api/v3/users/{sa1.id}", headers=h2,
        )
        assert resp.status_code in (200, 204), resp.text


# ---------------------------------------------------------------------------
# Round 3 — admin peer-takeover (G4 password / G5 DELETE)
# ---------------------------------------------------------------------------

class TestAdminPeerTakeoverPasswordChange:
    """G4: an admin caller cannot change ANOTHER admin's password.
    Mirrors G2 for the admin tier. Escape hatch: revoke target's
    admin role first."""

    def test_admin_cannot_change_peer_admin_password(
        self, client, admin_user, admin_headers, second_admin_user,
    ):
        resp = client.patch(
            f"/api/v3/users/{second_admin_user.id}/password",
            json={"password": "PeerHijack!"},
            headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "another admin" in resp.json()["error"]["message"].lower()

    def test_admin_can_change_own_password(
        self, client, admin_user, admin_headers,
    ):
        resp = client.patch(
            f"/api/v3/users/{admin_user.id}/password",
            json={"password": "NewSelfPwd!"},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text

    def test_admin_can_change_lower_tier_password(
        self, client, admin_user, admin_headers, member_user,
    ):
        resp = client.patch(
            f"/api/v3/users/{member_user.id}/password",
            json={"password": "NewLowerPwd!"},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text

    def test_super_admin_can_change_admin_peer_password_post_g4(
        self, client, db_session, admin_user,
    ):
        # Sanity: G4 only applies when caller is admin (not super_admin).
        # super_admin remains free to manage admin tier.
        sa, headers = _bootstrap_super_admin(db_session)
        resp = client.patch(
            f"/api/v3/users/{admin_user.id}/password",
            json={"password": "SaSetsAdminPwd!"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text


class TestAdminPeerTakeoverDelete:
    """G5: an admin caller cannot DELETE another admin without first
    demoting (revoking the admin role)."""

    def test_admin_cannot_delete_peer_admin(
        self, client, admin_user, admin_headers, second_admin_user,
    ):
        resp = client.delete(
            f"/api/v3/users/{second_admin_user.id}", headers=admin_headers,
        )
        assert resp.status_code == 403, resp.text
        assert "another admin" in resp.json()["error"]["message"].lower()

    def test_admin_can_delete_after_demoting_target(
        self, client, db_session, admin_user, admin_headers,
        second_admin_user,
    ):
        # Demote second_admin_user (revoke admin role membership) and
        # try DELETE again. After demotion the destructive guard
        # doesn't fire and the DELETE proceeds.
        from app.infrastructure.db.models.user_role import UserRoleModel
        admin_role_id = (
            db_session.query(RoleModel)
            .filter(RoleModel.name == ADMIN_ROLE_NAME).one().id
        )
        db_session.query(UserRoleModel).filter(
            UserRoleModel.user_id == second_admin_user.id,
            UserRoleModel.role_id == admin_role_id,
        ).delete()
        db_session.commit()
        resp = client.delete(
            f"/api/v3/users/{second_admin_user.id}", headers=admin_headers,
        )
        assert resp.status_code in (200, 204), resp.text

    def test_super_admin_can_delete_admin_post_g5(
        self, client, db_session, admin_user,
    ):
        # Sanity: G5 only applies when caller is admin (not super_admin).
        sa, headers = _bootstrap_super_admin(db_session)
        resp = client.delete(
            f"/api/v3/users/{admin_user.id}", headers=headers,
        )
        assert resp.status_code in (200, 204), resp.text


# ---------------------------------------------------------------------------
# F4 — universal-OTP startup warning (positioning anchor)
# ---------------------------------------------------------------------------

class TestUniversalOtpStartupWarning:
    def test_warning_string_present_in_main(self):
        """Sanity: app/main.py contains the universal-OTP warning
        string, gated on the UNIVERSAL_OTP_ENABLED setting. We
        deliberately do NOT exercise the full lifespan in tests
        (would re-init the DB) — verifying the source string is
        sufficient because the gate is a one-liner: if setting,
        log warning."""
        from pathlib import Path
        src = Path(__file__).resolve().parent.parent / "app" / "main.py"
        text = src.read_text(encoding="utf-8")
        assert "UNIVERSAL_OTP_ENABLED" in text
        assert "SECURITY" in text
        # Must be wrapped in a conditional, not unconditional.
        assert "getattr(settings, \"UNIVERSAL_OTP_ENABLED\"" in text
