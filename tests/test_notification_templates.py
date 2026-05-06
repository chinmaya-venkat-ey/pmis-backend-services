"""Tests for the notification_templates master endpoints.

Mirrors the relevant parts of monolith's test_doc36_notification_
templates.py — adapted for notification-service's smaller test infra
(no shared conftest fixtures for users/roles, so we craft Bearer
tokens directly via core.security helpers and seed the RBAC tables
ourselves).
"""
from __future__ import annotations

import time
import uuid

import jwt
import pytest


# DB / SECRET_KEY env vars set in tests/conftest.py BEFORE the app
# module loads, so the engine + middleware see the right values.


@pytest.fixture
def client_with_seed():
    """TestClient backed by an in-memory SQLite + seeded RBAC + templates."""
    from sqlalchemy import text
    from app.db.session import Base, SessionLocal, engine
    import app.db.models  # noqa: F401 — registers models on Base

    # Create user-service-owned tables that this service reads (RBAC).
    # Lightweight: we only need users / roles / permissions /
    # role_permissions / user_roles / revoked_tokens.
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=engine)
        # Hand-roll the RBAC tables since user-service models aren't
        # imported here.
        for ddl in (
            "CREATE TABLE IF NOT EXISTS users (id VARCHAR(36) PRIMARY KEY, login VARCHAR(255))",
            "CREATE TABLE IF NOT EXISTS roles (id INTEGER PRIMARY KEY, name VARCHAR(255))",
            "CREATE TABLE IF NOT EXISTS permissions (code VARCHAR(128) PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS role_permissions ("
            "role_id INTEGER, permission_code VARCHAR(128), "
            "PRIMARY KEY (role_id, permission_code))",
            "CREATE TABLE IF NOT EXISTS user_roles ("
            "user_id VARCHAR(36), role_id INTEGER, "
            "PRIMARY KEY (user_id, role_id))",
            "CREATE TABLE IF NOT EXISTS user_permissions ("
            "user_id VARCHAR(36), permission_code VARCHAR(128), "
            "PRIMARY KEY (user_id, permission_code))",
            "CREATE TABLE IF NOT EXISTS revoked_tokens (jti VARCHAR(64) PRIMARY KEY)",
            # Wipe rows so per-test fixture invocations don't collide.
            "DELETE FROM users",
            "DELETE FROM roles",
            "DELETE FROM permissions",
            "DELETE FROM role_permissions",
            "DELETE FROM user_roles",
            "DELETE FROM user_permissions",
            "DELETE FROM revoked_tokens",
            "DELETE FROM notification_templates",
        ):
            db.execute(text(ddl))
        # Insert an admin user with master_data:view + master_data:manage perms.
        admin_uuid = str(uuid.uuid4())
        db.execute(
            text("INSERT INTO users (id, login) VALUES (:id, :login)"),
            {"id": admin_uuid, "login": "admin"},
        )
        db.execute(text("INSERT INTO roles (id, name) VALUES (1, 'admin')"))
        db.execute(
            text("INSERT INTO permissions (code) VALUES ('master_data:view')"),
        )
        db.execute(
            text("INSERT INTO permissions (code) VALUES ('master_data:manage')"),
        )
        db.execute(
            text("INSERT INTO role_permissions (role_id, permission_code) "
                 "VALUES (1, 'master_data:view')"),
        )
        db.execute(
            text("INSERT INTO role_permissions (role_id, permission_code) "
                 "VALUES (1, 'master_data:manage')"),
        )
        db.execute(
            text("INSERT INTO user_roles (user_id, role_id) "
                 "VALUES (:uid, 1)"),
            {"uid": admin_uuid},
        )

        # Seed templates via init_db logic.
        from app.db.session import _seed_built_in_templates
        from app.db.models.notification_template import NotificationTemplateModel
        _seed_built_in_templates(db, NotificationTemplateModel)
        db.commit()
    finally:
        db.close()

    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app), admin_uuid


def _admin_token(user_id: str) -> str:
    """Mint a JWT the way user-service would."""
    payload = {
        "sub": "admin",
        "user_id": user_id,
        "email": "admin@example.com",
        "jti": "test-jti-1",
        "iat": int(time.time()),
        "exp": int(time.time()) + 900,
    }
    return jwt.encode(
        payload,
        "shared-test-secret-key-32-chars-min-shared-test",
        algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# Seed visibility
# ---------------------------------------------------------------------------

class TestSeed:
    def test_six_seed_rows_present(self, client_with_seed):
        client, uid = client_with_seed
        resp = client.get(
            "/api/v3/master/notification_templates",
            headers={"Authorization": f"Bearer {_admin_token(uid)}"},
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()["data"]["_embedded"]["elements"]
        kinds = {(r["templateKind"], r["channel"]) for r in rows}
        assert kinds == {
            ("otp_login", "email"),
            ("otp_login", "sms"),
            ("password_reset_link", "email"),
            ("password_reset_link", "sms"),
            ("password_reset_otp", "email"),
            ("password_reset_otp", "sms"),
        }
        for r in rows:
            assert r["isBuiltin"] is True


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    def test_no_token_returns_401(self, client_with_seed):
        client, _ = client_with_seed
        resp = client.get("/api/v3/master/notification_templates")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client_with_seed):
        client, _ = client_with_seed
        resp = client.get(
            "/api/v3/master/notification_templates",
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestCRUD:
    def test_create_custom_template(self, client_with_seed):
        client, uid = client_with_seed
        resp = client.post(
            "/api/v3/master/notification_templates/create",
            headers={"Authorization": f"Bearer {_admin_token(uid)}"},
            json={
                "templateKind": "custom_kind",
                "channel": "email",
                "subject": "Hello {name}",
                "body": "<p>Hi {name}</p>",
            },
        )
        assert resp.status_code == 201, resp.text

    def test_create_duplicate_active_returns_409(self, client_with_seed):
        client, uid = client_with_seed
        # otp_login + email is already seeded as active.
        resp = client.post(
            "/api/v3/master/notification_templates/create",
            headers={"Authorization": f"Bearer {_admin_token(uid)}"},
            json={
                "templateKind": "otp_login",
                "channel": "email",
                "subject": "Different subject",
                "body": "<p>{code}</p>",
            },
        )
        assert resp.status_code == 409, resp.text

    def test_unknown_placeholder_rejected(self, client_with_seed):
        client, uid = client_with_seed
        # otp_login allows {code}, {ttl_minutes}; reject anything else.
        # First deactivate the seeded row.
        list_resp = client.get(
            "/api/v3/master/notification_templates",
            headers={"Authorization": f"Bearer {_admin_token(uid)}"},
        )
        tmpl_id = next(
            r["id"] for r in list_resp.json()["data"]["_embedded"]["elements"]
            if r["templateKind"] == "otp_login" and r["channel"] == "email"
        )
        client.delete(
            f"/api/v3/master/notification_templates/{tmpl_id}",
            headers={"Authorization": f"Bearer {_admin_token(uid)}"},
        )
        resp = client.post(
            "/api/v3/master/notification_templates/create",
            headers={"Authorization": f"Bearer {_admin_token(uid)}"},
            json={
                "templateKind": "otp_login",
                "channel": "email",
                "subject": "OTP {oops}",
                "body": "<p>{code}</p>",
            },
        )
        assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Renderer integration (unit-level)
# ---------------------------------------------------------------------------

class TestRenderer:
    def test_render_email_substitutes_placeholders(self, client_with_seed):
        from app.db.session import SessionLocal
        from app.services.template_service import render_email
        client, _ = client_with_seed  # unused but ensures seed
        db = SessionLocal()
        try:
            subject, body, is_html = render_email(
                db, "otp_login", {"code": "987654", "ttl_seconds": 300},
            )
            assert "987654" in body
            assert "5 minutes" in body
            assert is_html is True
            assert subject
        finally:
            db.close()

    def test_render_sms_substitutes_placeholders(self, client_with_seed):
        from app.db.session import SessionLocal
        from app.services.template_service import render_sms
        client, _ = client_with_seed
        db = SessionLocal()
        try:
            msg = render_sms(
                db, "otp_login", {"code": "112233", "ttl_seconds": 300},
            )
            assert "112233" in msg
            assert "5 min" in msg
        finally:
            db.close()
