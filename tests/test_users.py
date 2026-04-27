"""Tests for user-management endpoints.

Ported from the monolith's ``tests/test_users.py`` — same coverage,
same assertions, adapted for the user-service's packaging. This proves
the extraction preserved behaviour 1:1.
"""
import pytest


class TestCreateUser:
    """POST /api/v3/users/create"""

    def test_create_user_success(self, client, admin_user, admin_headers):
        resp = client.post("/api/v3/users/create", json={
            "login": "newuser",
            "email": "new@example.com",
            "password": "password123",
            "firstName": "New",
            "lastName": "User",
            "admin": False,
        }, headers=admin_headers)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["login"] == "newuser"
        assert data["email"] == "new@example.com"
        assert data["_type"] == "User"
        assert "id" in data

    def test_create_user_duplicate_login(self, client, admin_user, admin_headers):
        client.post("/api/v3/users/create", json={
            "login": "dup", "email": "a@a.com", "password": "password123",
        }, headers=admin_headers)
        resp = client.post("/api/v3/users/create", json={
            "login": "dup", "email": "b@b.com", "password": "password123",
        }, headers=admin_headers)
        assert resp.status_code == 409

    def test_create_user_duplicate_email(self, client, admin_user, admin_headers):
        client.post("/api/v3/users/create", json={
            "login": "user1", "email": "same@example.com", "password": "password123",
        }, headers=admin_headers)
        resp = client.post("/api/v3/users/create", json={
            "login": "user2", "email": "same@example.com", "password": "password123",
        }, headers=admin_headers)
        assert resp.status_code == 409

    def test_create_user_invalid_email(self, client, admin_user, admin_headers):
        resp = client.post("/api/v3/users/create", json={
            "login": "badmail", "email": "not-an-email", "password": "password123",
        }, headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_short_password(self, client, admin_user, admin_headers):
        resp = client.post("/api/v3/users/create", json={
            "login": "shortpw", "email": "s@s.com", "password": "short",
        }, headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_short_login(self, client, admin_user, admin_headers):
        resp = client.post("/api/v3/users/create", json={
            "login": "ab", "email": "ab@ab.com", "password": "password123",
        }, headers=admin_headers)
        assert resp.status_code == 422

    def test_create_user_missing_required(self, client, admin_user, admin_headers):
        resp = client.post(
            "/api/v3/users/create", json={"login": "only"}, headers=admin_headers,
        )
        assert resp.status_code == 422


class TestListUsers:
    """GET /api/v3/users"""

    def test_list_users(self, client, admin_user, admin_headers):
        resp = client.get("/api/v3/users?offset=1&pageSize=10", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["_type"] == "Collection"
        assert body["total"] >= 1
        assert "_embedded" in body
        assert "elements" in body["_embedded"]

    def test_list_users_pagination(self, client, admin_user, member_user, admin_headers):
        resp = client.get("/api/v3/users?offset=1&pageSize=1", headers=admin_headers)
        body = resp.json()["data"]
        assert body["count"] == 1
        assert body["pageSize"] == 1

    def test_list_users_forbidden_for_member(
        self, client, admin_user, member_user, member_headers,
    ):
        resp = client.get("/api/v3/users", headers=member_headers)
        assert resp.status_code == 403


class TestGetUser:
    """GET /api/v3/users/{id}"""

    def test_get_user_by_id(self, client, admin_user, admin_headers):
        resp = client.get(f"/api/v3/users/{admin_user.id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["login"] == "admin"

    def test_get_nonexistent_user(self, client, admin_user, admin_headers):
        resp = client.get("/api/v3/users/99999", headers=admin_headers)
        # Monolith behaviour: 200 with error body or 404, both acceptable.
        assert resp.status_code in [200, 404]


class TestUpdateUser:
    """PATCH /api/v3/users/{id}"""

    def test_update_user(self, client, admin_user, member_user, admin_headers):
        resp = client.patch(f"/api/v3/users/{member_user.id}", json={
            "firstName": "Updated",
            "lastName": "Name",
        }, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["firstName"] == "Updated"

    def test_update_password(self, client, admin_user, member_user, admin_headers):
        resp = client.patch(f"/api/v3/users/{member_user.id}/password", json={
            "password": "newpassword123",
        }, headers=admin_headers)
        assert resp.status_code == 200


class TestDeleteUser:
    """DELETE /api/v3/users/{id}"""

    def test_delete_user(self, client, admin_user, member_user, admin_headers):
        resp = client.delete(f"/api/v3/users/{member_user.id}", headers=admin_headers)
        assert resp.status_code == 200

    def test_delete_nonexistent_user(self, client, admin_user, admin_headers):
        resp = client.delete("/api/v3/users/99999", headers=admin_headers)
        assert resp.status_code in [200, 404]


# ===========================================================================
# Login + Logout (hard logout — jti blacklist + refresh revoke)
# ===========================================================================

class TestLogin:
    def test_login_success(self, client, admin_user):
        resp = client.post("/api/v3/users/login", json={
            "login": "admin", "password": "admin123",
        })
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["_type"] == "Login"
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["user"]["login"] == "admin"

    def test_login_wrong_password(self, client, admin_user):
        resp = client.post("/api/v3/users/login", json={
            "login": "admin", "password": "wrong",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/api/v3/users/login", json={
            "login": "nope", "password": "whatever",
        })
        assert resp.status_code == 401


class TestLogout:
    """Hard logout — ported from the monolith verbatim."""

    def _login(self, client, login: str, password: str):
        resp = client.post(
            "/api/v3/users/login", json={"login": login, "password": password},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        return (
            data["access_token"],
            data["refresh_token"],
            {"Authorization": f"Bearer {data['access_token']}"},
        )

    def test_logout_success(self, client, admin_user, admin_headers):
        resp = client.post("/api/v3/users/logout", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["_type"] == "Success"
        assert "logged out" in body["data"]["message"].lower()

    def test_logout_blacklists_access_token(self, client, admin_user):
        access, _refresh, headers = self._login(client, "admin", "admin123")

        me = client.get("/api/v3/users/me", headers=headers)
        assert me.status_code == 200

        out = client.post("/api/v3/users/logout", headers=headers)
        assert out.status_code == 200, out.text

        me_after = client.get("/api/v3/users/me", headers=headers)
        assert me_after.status_code == 401, me_after.text

    def test_logout_clears_refresh_token(self, client, admin_user, db_session):
        from app.infrastructure.db.models.user import UserModel
        access, _refresh, headers = self._login(client, "admin", "admin123")

        db_session.expire_all()
        u_before = db_session.query(UserModel).filter_by(login="admin").one()
        assert u_before.refresh_token_jti is not None

        client.post("/api/v3/users/logout", headers=headers)

        db_session.expire_all()
        u_after = db_session.query(UserModel).filter_by(login="admin").one()
        assert u_after.refresh_token_jti is None
        assert u_after.refresh_token_expires_at is None

    def test_logout_invalidates_refresh_endpoint(self, client, admin_user):
        _access, refresh, headers = self._login(client, "admin", "admin123")

        client.post("/api/v3/users/logout", headers=headers)

        intro = client.post(
            "/api/v3/users/introspect", json={"refresh_token": refresh},
        )
        assert intro.status_code == 401, intro.text

    def test_logout_inserts_blacklist_row(self, client, admin_user, db_session):
        from datetime import datetime, timezone
        from app.infrastructure.db.models.revoked_token import RevokedTokenModel

        access, _refresh, headers = self._login(client, "admin", "admin123")

        client.post("/api/v3/users/logout", headers=headers)
        db_session.expire_all()

        rows = db_session.query(RevokedTokenModel).filter_by(
            user_id=admin_user.id,
        ).all()
        assert len(rows) == 1
        row = rows[0]
        # SQLite returns naive datetimes; strip tz for naive comparison.
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        assert row.expires_at > now_naive, \
            "blacklist row's expires_at must be in the future"

    def test_logout_idempotent(self, client, admin_user, admin_headers):
        first = client.post("/api/v3/users/logout", headers=admin_headers)
        assert first.status_code == 200, first.text

        second = client.post("/api/v3/users/logout", headers=admin_headers)
        # Middleware now treats the token as revoked.
        assert second.status_code == 401, second.text

    def test_logout_without_auth_rejected(self, client):
        resp = client.post("/api/v3/users/logout")
        assert resp.status_code == 401

    def test_logout_with_invalid_token_rejected(self, client):
        resp = client.post(
            "/api/v3/users/logout",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401

    def test_logout_does_not_affect_other_users(self, client, admin_user):
        admin_resp = client.post(
            "/api/v3/users/login",
            json={"login": "admin", "password": "admin123"},
        )
        admin_token = admin_resp.json()["data"]["access_token"]
        admin_h = {"Authorization": f"Bearer {admin_token}"}

        client.post(
            "/api/v3/users/create",
            json={
                "login": "userb", "email": "b@b.com", "password": "passwordB1",
            },
            headers=admin_h,
        )

        _a_access, _a_refresh, a_headers = self._login(client, "admin", "admin123")
        b_access, _b_refresh, b_headers = self._login(client, "userb", "passwordB1")

        out_a = client.post("/api/v3/users/logout", headers=a_headers)
        assert out_a.status_code == 200

        me_b = client.get("/api/v3/users/me", headers=b_headers)
        assert me_b.status_code == 200, me_b.text

    def test_login_after_logout_works(self, client, admin_user):
        _access, _refresh, headers = self._login(client, "admin", "admin123")
        client.post("/api/v3/users/logout", headers=headers)

        resp = client.post(
            "/api/v3/users/login",
            json={"login": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200, resp.text
        new_token = resp.json()["data"]["access_token"]

        me = client.get(
            "/api/v3/users/me",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        assert me.status_code == 200


# ===========================================================================
# Introspect + refresh rotation
# ===========================================================================

class TestIntrospect:
    def _login(self, client, login: str, password: str):
        resp = client.post(
            "/api/v3/users/login", json={"login": login, "password": password},
        )
        assert resp.status_code == 200
        return resp.json()["data"]

    def test_introspect_valid_access_token(self, client, admin_user):
        data = self._login(client, "admin", "admin123")
        resp = client.post(
            "/api/v3/users/introspect",
            json={"access_token": data["access_token"]},
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["active"] is True
        assert body["user"]["login"] == "admin"

    def test_introspect_refresh_rotation(self, client, admin_user):
        data = self._login(client, "admin", "admin123")
        resp = client.post(
            "/api/v3/users/introspect",
            json={"refresh_token": data["refresh_token"]},
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["access_token"]
        assert body["refresh_token"]
        # Rotated — new refresh token must differ from the old.
        assert body["refresh_token"] != data["refresh_token"]

    def test_introspect_empty_payload_rejected(self, client):
        resp = client.post("/api/v3/users/introspect", json={})
        assert resp.status_code == 401

    def test_introspect_reused_refresh_rejected(self, client, admin_user):
        """Once a refresh token has been rotated, the old one must be rejected."""
        data = self._login(client, "admin", "admin123")
        # First use — rotates.
        first = client.post(
            "/api/v3/users/introspect",
            json={"refresh_token": data["refresh_token"]},
        )
        assert first.status_code == 200
        # Second use of the OLD refresh token — must fail.
        second = client.post(
            "/api/v3/users/introspect",
            json={"refresh_token": data["refresh_token"]},
        )
        assert second.status_code == 401


# ===========================================================================
# /me
# ===========================================================================

class TestMe:
    def test_me_with_valid_token(self, client, admin_user, admin_headers):
        resp = client.get("/api/v3/users/me", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["login"] == "admin"

    def test_me_without_auth_rejected(self, client):
        resp = client.get("/api/v3/users/me")
        assert resp.status_code == 401
