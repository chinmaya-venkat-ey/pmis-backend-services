"""Mirror of monolith Doc 44 round 8 + Doc 46 round 11 — three changes
that don't depend on the doc-41 scoped RBAC backport (which is not yet
on project-service):

  1. ``GET /projects``  → non-admin tiers see only post-publish
     projects (status not in {draft, new}).
  2. ``GET /projects/{id}`` → 404 when the project is pre-publish and
     the caller is non-admin.
  3. ``GET /vendors/{id}`` → non-admin can only fetch their own vendor
     (``users.vendor_id`` match), else 403.
  4. ``POST /vendors/create`` + ``PATCH /vendors/{id}`` → vendor
     email uniqueness across all vendor rows (incl. soft-deleted).

The PATCH allowlist (doc 44 round 9) and the assignable-users endpoint
(doc 46 round 11b) are intentionally NOT mirrored — they depend on the
``user_role_assignment`` model and ``org_admin`` seed role which the
project-service RBAC seed doesn't have yet.
"""
from uuid import uuid4

import pytest

from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.vendor import VendorModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(db, *, name, status="published", owner="tmd1"):
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"UIDAI-PR{uuid4().hex[:10]}",
        name=name,
        status=status,
        owner=owner,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_vendor(db, *, name, email=None, active=True):
    v = VendorModel(
        id=str(uuid4()),
        vendor_code=f"VN-{uuid4().hex[:8]}",
        name=name,
        active=active,
        email=email,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def _bind_member_to_vendor(db, vendor_id: str):
    """Attach the member fixture user to a vendor by setting
    ``users.vendor_id``. Returns the user."""
    from tests.conftest import _MEMBER_UUID
    user = db.query(UserModel).filter(UserModel.id == _MEMBER_UUID).first()
    assert user is not None, (
        "member_user fixture must run first — depend on member_headers in "
        "the test signature."
    )
    user.vendor_id = vendor_id
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# 1 + 2. Pre-publish project hide
# ---------------------------------------------------------------------------

class TestPrePublishProjectHide:
    def test_admin_sees_pre_publish_projects_in_list(
        self, client, admin_headers, db_session,
    ):
        _make_project(db_session, name="P-pub", status="published")
        _make_project(db_session, name="P-draft", status="draft")
        _make_project(db_session, name="P-new", status="new")
        r = client.get("/api/v3/projects", headers=admin_headers)
        assert r.status_code == 200, r.text
        names = [p["name"] for p in r.json()["data"]["_embedded"]["elements"]]
        assert "P-pub" in names
        assert "P-draft" in names
        assert "P-new" in names

    def test_member_hidden_from_pre_publish_projects_in_list(
        self, client, member_headers, db_session,
    ):
        _make_project(db_session, name="P-pub", status="published")
        _make_project(db_session, name="P-draft", status="draft")
        _make_project(db_session, name="P-new", status="new")
        r = client.get("/api/v3/projects", headers=member_headers)
        assert r.status_code == 200, r.text
        names = [p["name"] for p in r.json()["data"]["_embedded"]["elements"]]
        assert names == ["P-pub"]

    def test_admin_can_fetch_pre_publish_project_directly(
        self, client, admin_headers, db_session,
    ):
        p = _make_project(db_session, name="P-draft", status="draft")
        r = client.get(f"/api/v3/projects/{p.id}", headers=admin_headers)
        assert r.status_code == 200, r.text

    def test_member_gets_404_on_pre_publish_single_fetch(
        self, client, member_headers, db_session,
    ):
        p = _make_project(db_session, name="P-draft", status="draft")
        r = client.get(f"/api/v3/projects/{p.id}", headers=member_headers)
        assert r.status_code == 404, r.text

    def test_member_can_fetch_published_project(
        self, client, member_headers, db_session,
    ):
        p = _make_project(db_session, name="P-pub", status="published")
        r = client.get(f"/api/v3/projects/{p.id}", headers=member_headers)
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 3. GET /vendors/{id} caller-vendor scope
# ---------------------------------------------------------------------------

class TestVendorReadScope:
    def test_admin_can_read_any_vendor(
        self, client, admin_headers, db_session,
    ):
        v = _make_vendor(db_session, name="V1")
        r = client.get(f"/api/v3/vendors/{v.id}", headers=admin_headers)
        assert r.status_code == 200, r.text

    def test_member_blocked_on_other_vendor(
        self, client, member_headers, db_session,
    ):
        v_mine = _make_vendor(db_session, name="Mine")
        v_other = _make_vendor(db_session, name="Other")
        _bind_member_to_vendor(db_session, v_mine.id)
        r = client.get(
            f"/api/v3/vendors/{v_other.id}", headers=member_headers,
        )
        assert r.status_code == 403, r.text
        assert "own organization" in r.text.lower()

    def test_member_can_read_own_vendor(
        self, client, member_headers, db_session,
    ):
        v_mine = _make_vendor(db_session, name="Mine")
        _bind_member_to_vendor(db_session, v_mine.id)
        r = client.get(
            f"/api/v3/vendors/{v_mine.id}", headers=member_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["name"] == "Mine"


# ---------------------------------------------------------------------------
# 4. Vendor email uniqueness
# ---------------------------------------------------------------------------

class TestVendorEmailUniqueness:
    def test_create_rejects_duplicate_email(
        self, client, admin_headers, db_session,
    ):
        _make_vendor(db_session, name="V1", email="ops@x.example.com")
        r = client.post(
            "/api/v3/vendors/create",
            headers=admin_headers,
            json={
                "name": "V2",
                "email": "ops@x.example.com",
                "phoneNumber": "+919999999999",
            },
        )
        assert r.status_code == 409, r.text
        assert "already exists" in r.text.lower()

    def test_create_rejects_case_insensitive(
        self, client, admin_headers, db_session,
    ):
        _make_vendor(db_session, name="V1", email="ops@x.example.com")
        r = client.post(
            "/api/v3/vendors/create",
            headers=admin_headers,
            json={
                "name": "V2",
                "email": "OPS@X.EXAMPLE.COM",
                "phoneNumber": "+919999999999",
            },
        )
        assert r.status_code == 409, r.text

    def test_create_against_soft_deleted_still_rejects(
        self, client, admin_headers, db_session,
    ):
        from datetime import datetime, timezone
        v = _make_vendor(db_session, name="OldV", email="dup@x.example.com")
        v.deleted_at = datetime.now(timezone.utc)
        db_session.commit()
        r = client.post(
            "/api/v3/vendors/create",
            headers=admin_headers,
            json={
                "name": "NewV",
                "email": "dup@x.example.com",
                "phoneNumber": "+919999999999",
            },
        )
        assert r.status_code == 409, r.text

    def test_patch_rejects_email_already_taken(
        self, client, admin_headers, db_session,
    ):
        v1 = _make_vendor(db_session, name="V1", email="a@x.example.com")
        v2 = _make_vendor(db_session, name="V2", email="b@x.example.com")
        r = client.patch(
            f"/api/v3/vendors/{v2.id}",
            headers=admin_headers,
            json={"email": "a@x.example.com"},
        )
        assert r.status_code == 409, r.text
        assert "already exists" in r.text.lower()

    def test_patch_same_email_is_noop_success(
        self, client, admin_headers, db_session,
    ):
        """Sending the vendor's own existing email back should succeed
        (no self-match collision)."""
        v = _make_vendor(db_session, name="V1", email="a@x.example.com")
        r = client.patch(
            f"/api/v3/vendors/{v.id}",
            headers=admin_headers,
            json={"email": "a@x.example.com"},
        )
        assert r.status_code == 200, r.text

    def test_patch_to_unique_email_succeeds(
        self, client, admin_headers, db_session,
    ):
        v = _make_vendor(db_session, name="V1", email="a@x.example.com")
        r = client.patch(
            f"/api/v3/vendors/{v.id}",
            headers=admin_headers,
            json={"email": "new@x.example.com"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["email"] == "new@x.example.com"
