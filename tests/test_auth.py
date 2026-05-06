"""Tests for authentication endpoints and flows."""
import pytest


class TestHealthAndRoot:
    """Public endpoints that require no authentication."""

    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        # User-mgmt returns {"status":"ok","service":"pmis-user-service",
        # "version":..., "secret_key_sha256_prefix":...}
        assert data["status"] == "ok"
        assert data["service"] == "pmis-user-service"

    def test_root_endpoint(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["_type"] == "Root"
        assert "_links" in data
        assert "self" in data["_links"]


class TestLogin:
    """Login endpoint tests."""

    def test_login_success(self, client, admin_user):
        resp = client.post("/api/v3/users/login", json={
            "login": "admin",
            "password": "admin123",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "access_token" in body["data"]
        assert body["data"]["token_type"] == "bearer"
        assert body["data"]["user"]["login"] == "admin"

    def test_login_invalid_password(self, client, admin_user):
        resp = client.post("/api/v3/users/login", json={
            "login": "admin",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client, admin_user):
        resp = client.post("/api/v3/users/login", json={
            "login": "nobody",
            "password": "password123",
        })
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/api/v3/users/login", json={"login": "admin"})
        assert resp.status_code == 422

    def test_login_empty_body(self, client):
        resp = client.post("/api/v3/users/login", json={})
        assert resp.status_code == 422


class TestProtectedAccess:
    """Verify authentication middleware blocks unauthenticated requests."""

    def test_no_token_returns_401(self, client, admin_user):
        resp = client.get("/api/v3/users/me")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client, admin_user):
        resp = client.get(
            "/api/v3/users/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401

    def test_malformed_header_returns_401(self, client, admin_user):
        resp = client.get(
            "/api/v3/users/me",
            headers={"Authorization": "NotBearer token"},
        )
        assert resp.status_code == 401

    def test_valid_token_returns_user(self, client, admin_user, admin_headers):
        resp = client.get("/api/v3/users/me", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["login"] == "admin"
        assert body["data"]["_type"] == "User"


class TestIntrospect:
    """Token introspection endpoint (RFC 7662 read-only metadata)."""

    def test_introspect_valid_token(self, client, admin_user, admin_token):
        resp = client.post("/api/v3/users/introspect", json={
            "access_token": admin_token,
        })
        assert resp.status_code == 200
        body = resp.json()
        d = body["data"]
        assert d["active"] is True
        assert d["tokenType"] == "access"
        assert d["sub"] == "admin"
        assert d["userId"] == admin_user.id
        assert d["isAdmin"] is True
        # Expiry / issued-at must be ISO 8601 strings the FE can parse.
        assert d["expiresAt"] and "T" in d["expiresAt"]
        assert d["issuedAt"] and "T" in d["issuedAt"]
        assert d["jti"]

    def test_introspect_no_token(self, client):
        resp = client.post("/api/v3/users/introspect", json={})
        assert resp.status_code in [400, 401, 422]

    def test_introspect_garbage_token_returns_inactive(self, client):
        """Unparseable token → 200 with active=false (RFC 7662 semantics)."""
        resp = client.post(
            "/api/v3/users/introspect",
            json={"access_token": "not-a-jwt"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["active"] is False
        assert body["tokenType"] == "access"

    def test_introspect_both_tokens_returns_split_shape(self, client, admin_user):
        """Supplying both access + refresh produces a split response with
        a per-token result under access / refresh keys."""
        login = client.post(
            "/api/v3/users/login",
            json={"login": "admin", "password": "admin123"},
        )
        assert login.status_code == 200
        ld = login.json()["data"]

        resp = client.post(
            "/api/v3/users/introspect",
            json={
                "access_token": ld["access_token"],
                "refresh_token": ld["refresh_token"],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["access"]["active"] is True
        assert body["access"]["tokenType"] == "access"
        assert body["refresh"]["active"] is True
        assert body["refresh"]["tokenType"] == "refresh"


class TestLoginMetadata:
    """Login response now carries token-expiry metadata so the FE doesn't
    have to decode the JWT to schedule a refresh."""

    def test_login_response_includes_expiry_metadata(self, client, admin_user):
        resp = client.post(
            "/api/v3/users/login",
            json={"login": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200, resp.text
        d = resp.json()["data"]
        assert d["accessTokenExpiresAt"] and "T" in d["accessTokenExpiresAt"]
        assert d["accessTokenIssuedAt"] and "T" in d["accessTokenIssuedAt"]
        assert d["refreshTokenExpiresAt"] and "T" in d["refreshTokenExpiresAt"]
        assert d["refreshTokenIssuedAt"] and "T" in d["refreshTokenIssuedAt"]
        assert isinstance(d["expiresInSeconds"], int)
        assert d["expiresInSeconds"] > 0


class TestRefresh:
    """Dedicated POST /users/refresh — rotation-only endpoint."""

    def _login(self, client):
        resp = client.post(
            "/api/v3/users/login",
            json={"login": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    def test_refresh_rotates_tokens(self, client, admin_user):
        """Valid refresh token → fresh access + refresh pair, both
        different from the originals."""
        ld = self._login(client)
        resp = client.post(
            "/api/v3/users/refresh",
            json={"refresh_token": ld["refresh_token"]},
        )
        assert resp.status_code == 200, resp.text
        nd = resp.json()["data"]
        assert nd["_type"] == "Refresh"
        assert nd["access_token"]
        assert nd["refresh_token"]
        assert nd["access_token"] != ld["access_token"]
        assert nd["refresh_token"] != ld["refresh_token"]
        assert nd["accessTokenExpiresAt"] and "T" in nd["accessTokenExpiresAt"]
        assert nd["refreshTokenExpiresAt"] and "T" in nd["refreshTokenExpiresAt"]
        assert isinstance(nd["expiresInSeconds"], int)
        assert nd["user"]["login"] == "admin"

    def test_refresh_old_token_accepted_within_grace_window(self, client, admin_user):
        """After a successful refresh, the OLD refresh token remains valid
        for ``REFRESH_TOKEN_GRACE_SECONDS`` so concurrent /refresh calls
        from the FE (timer + 401 interceptor + multi-tab) don't 401 the
        loser. Both calls get their own fresh pair."""
        ld = self._login(client)
        first = client.post(
            "/api/v3/users/refresh",
            json={"refresh_token": ld["refresh_token"]},
        )
        assert first.status_code == 200
        nd1 = first.json()["data"]

        # Re-using the original refresh inside the grace window still works.
        second = client.post(
            "/api/v3/users/refresh",
            json={"refresh_token": ld["refresh_token"]},
        )
        assert second.status_code == 200, second.text
        nd2 = second.json()["data"]
        # Each call mints its OWN fresh pair — they aren't shared.
        assert nd2["refresh_token"] not in (
            ld["refresh_token"], nd1["refresh_token"],
        )

    def test_refresh_same_token_works_twice_back_to_back(self, client, admin_user):
        """Modelling the FE race: two /refresh calls with the SAME RT, fired
        as close together as the test client allows. Both succeed — the
        first rotates the live jti, the second is absorbed by the grace
        window. This is the user-visible behaviour fix.

        (A truly threaded version of this test trips SQLite's global-write
        lock; Postgres handles it cleanly with row-level locks.)
        """
        ld = self._login(client)
        first = client.post(
            "/api/v3/users/refresh",
            json={"refresh_token": ld["refresh_token"]},
        )
        second = client.post(
            "/api/v3/users/refresh",
            json={"refresh_token": ld["refresh_token"]},
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        # Each call mints its own pair, and both pairs differ from the
        # original login pair.
        rt0 = ld["refresh_token"]
        rt1 = first.json()["data"]["refresh_token"]
        rt2 = second.json()["data"]["refresh_token"]
        assert len({rt0, rt1, rt2}) == 3

    def test_refresh_after_relogin_still_works_in_grace(
        self, client, admin_user
    ):
        """A second login rotates the user's stored jti. The pre-relogin
        refresh token must still mint successfully while the grace window
        is open — this prevents tab-A getting locked out the moment tab-B
        opens and logs in."""
        first_login = self._login(client)
        # Second login from "another tab" — rotates the stored jti and
        # captures the original into the grace slot.
        self._login(client)
        # First-login token still works, because the grace window is open.
        resp = client.post(
            "/api/v3/users/refresh",
            json={"refresh_token": first_login["refresh_token"]},
        )
        assert resp.status_code == 200, resp.text

    def test_logout_clears_grace_window(self, client, admin_user):
        """Logout must clear BOTH the live jti and the grace-window slot —
        no user-visible session may survive an explicit logout, even if a
        refresh just happened a moment before."""
        ld = self._login(client)
        rotated = client.post(
            "/api/v3/users/refresh",
            json={"refresh_token": ld["refresh_token"]},
        )
        assert rotated.status_code == 200
        rotated_rt = rotated.json()["data"]["refresh_token"]

        # Logout using the access token from the freshly-issued pair.
        new_access = rotated.json()["data"]["access_token"]
        client.post(
            "/api/v3/users/logout",
            headers={"Authorization": f"Bearer {new_access}"},
        )

        # Grace-slot RT (original ld) and the live RT (rotated) both fail.
        for rt in (ld["refresh_token"], rotated_rt):
            r = client.post(
                "/api/v3/users/refresh",
                json={"refresh_token": rt},
            )
            assert r.status_code == 401, r.text

    def test_refresh_garbage_token_returns_401(self, client):
        resp = client.post(
            "/api/v3/users/refresh",
            json={"refresh_token": "not-a-jwt"},
        )
        assert resp.status_code == 401, resp.text

    def test_refresh_missing_body_returns_422(self, client):
        resp = client.post("/api/v3/users/refresh", json={})
        # Pydantic catches missing required field → 422
        assert resp.status_code == 422, resp.text

    def test_refresh_uses_access_token_as_refresh_returns_401(self, client, admin_user, admin_token):
        """Posting an access_token as refresh_token must fail — they're
        different audiences (different secrets / claims)."""
        resp = client.post(
            "/api/v3/users/refresh",
            json={"refresh_token": admin_token},
        )
        assert resp.status_code == 401, resp.text
