"""Doc 44 round 8 — project_admin gains ``users:read_all``.

Spec: "For Project Admins, the Organizations list and Users list are
currently not being displayed." The Vendors side already worked
(project_admin holds ``vendors:read``); the Users side was blocked
because ``GET /api/v3/users`` requires ``users:read_all`` and the
project_admin seed only had ``users:read``.

This file pins:
  * The seed change — ``project_admin`` carries ``users:read_all``.
  * The route works for a PA caller.
  * The round-7 vendor-scope filter still fires — PA sees only
    own-vendor users (no cross-vendor leak from the new perm).
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
        name=name or f"V-{uuid4().hex[:5]}",
        description="-", active=True,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def _make_pa(db, login, vendor_id):
    """Create a project_admin user (globally scoped row so the route
    gate sees the perm without needing a project context)."""
    RbacRepository(db).sync_builtin_permissions()
    db.commit()
    role_id = (
        db.query(RoleModel).filter(RoleModel.name == "project_admin").one().id
    )
    user = UserModel(
        login=login,
        email=f"{login}@example.com",
        hashed_password=hash_password("Pmis@1234"),
        first_name="P", last_name="A",
        status="active", two_factor_enabled=False,
        vendor_id=vendor_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(UserRoleAssignmentModel(
        user_id=user.id, role_id=role_id,
    ))
    db.commit()
    return user, {
        "Authorization": "Bearer " + create_access_token({
            "sub": user.login, "user_id": user.id, "email": user.email,
        })
    }


def _plain(db, login, vendor_id):
    user = UserModel(
        login=login,
        email=f"{login}@example.com",
        hashed_password=hash_password("Pmis@1234"),
        first_name="P", last_name="U",
        status="active", two_factor_enabled=False,
        vendor_id=vendor_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

class TestProjectAdminSeedHasUsersReadAll:
    def test_seed_includes_users_read_all(self, db_session, admin_user):
        codes = set(
            RbacRepository(db_session).list_role_permissions(
                db_session.query(RoleModel).filter(
                    RoleModel.name == "project_admin"
                ).one().id
            )
        )
        # Round 8 spec — the list endpoint now answers PA callers.
        assert "users:read_all" in codes
        # Sanity — round-5 set still intact.
        assert "users:read" in codes
        assert "users:deactivate" in codes


# ---------------------------------------------------------------------------
# Route + vendor-scope filter
# ---------------------------------------------------------------------------

class TestProjectAdminCanListUsers:
    def test_pa_get_users_returns_200(self, client, db_session):
        v = _vendor(db_session, "PAList-Own")
        _, pa_headers = _make_pa(db_session, "pa_list_ok", vendor_id=v.id)

        resp = client.get("/api/v3/users", headers=pa_headers)
        assert resp.status_code == 200, resp.text

    def test_pa_only_sees_own_vendor_users(self, client, db_session):
        v_own = _vendor(db_session, "PAList-Scope")
        v_other = _vendor(db_session, "PAList-Other")
        _, pa_headers = _make_pa(db_session, "pa_list_scope", vendor_id=v_own.id)

        in_scope = _plain(db_session, "in_scope_user", vendor_id=v_own.id)
        out_scope = _plain(db_session, "out_scope_user", vendor_id=v_other.id)

        resp = client.get("/api/v3/users?pageSize=100", headers=pa_headers)
        assert resp.status_code == 200, resp.text
        logins = {
            u["login"]
            for u in resp.json()["data"]["_embedded"]["elements"]
        }
        assert in_scope.login in logins
        assert out_scope.login not in logins
