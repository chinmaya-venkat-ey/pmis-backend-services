"""Tests for ``GET /api/v3/projects/{project_uuid}/audit-logs`` and the
doc-47 audit-log enrichment (mirror of monolith).

Coverage:
  * 404 on unknown project
  * empty audit list shape (top-level ``project`` block, _embedded, pagination keys)
  * project.create flow writes an audit row carrying the new
    denormalized snapshot fields (project_name/status/owner/
    actor_login/actor_code/actor_role)
  * the response row exposes them as camelCase
    (actorLogin/actorCode/actorRole) and the project block carries
    projectId/projectCode/projectName/projectStatus/owner
  * project rename does not retroactively change the existing audit
    row's snapshotted projectName — the snapshot is immutable
  * pagination
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.config import settings
from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.project_audit_log import ProjectAuditLogModel


@pytest.fixture(scope="function")
def project_id(db_session):
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"UIDAI-PR{uuid4().hex[:14].upper()}",
        name=f"P-{uuid4().hex[:6]}",
        description="-",
        active=True, public=False, status="new",
        owner="tmd1",
        start_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    db_session.add(p)
    db_session.commit()
    return p.id


# ===========================================================================
# Endpoint shape + 404 coverage
# ===========================================================================

class TestAuditLogsEndpoint:
    def test_404_on_unknown_project(self, client, admin_headers):
        r = client.get(
            f"/api/v3/projects/{uuid4()}/audit-logs",
            headers=admin_headers,
        )
        assert r.status_code == 404, r.text

    def test_empty_project_has_empty_audit_list(
        self, client, admin_headers, project_id, db_session,
    ):
        # Project fixture inserts the row directly (no audit row written).
        r = client.get(
            f"/api/v3/projects/{project_id}/audit-logs",
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["_type"] == "Collection"
        assert data["total"] == 0
        assert data["count"] == 0
        assert data["_embedded"]["elements"] == []
        # Top-level project block is present even on an empty audit list.
        proj = data["project"]
        assert proj["projectId"] == project_id
        assert proj["projectName"].startswith("P-")
        assert proj["projectCode"].startswith("UIDAI-PR")
        assert proj["projectStatus"] == "new"
        assert proj["owner"] == "tmd1"


# ===========================================================================
# record_audit -> denormalized snapshot persistence
# ===========================================================================

class TestAuditLogSnapshotCapture:
    def test_create_project_writes_enriched_audit_row(
        self, client, admin_headers, db_session,
    ):
        r = client.post(
            "/api/v3/projects/create",
            headers=admin_headers,
            json={
                "name": "Enriched Audit Project",
                "owner": "tmd1",
                "startDate": "2026-07-01T00:00:00+05:30",
                "endDate": "2026-12-31T00:00:00+05:30",
            },
        )
        assert r.status_code == 201, r.text
        pid = r.json()["data"]["id"]

        # Read raw row to assert snapshot columns populated.
        row = (
            db_session.query(ProjectAuditLogModel)
            .filter(ProjectAuditLogModel.project_id == pid)
            .filter(ProjectAuditLogModel.action == "project.create")
            .first()
        )
        assert row is not None
        # Snapshot fields are all populated (none NULL).
        assert row.project_name == "Enriched Audit Project"
        assert row.project_status  # whatever the create flow sets ('new' or 'draft')
        assert row.owner == "tmd1"
        # Admin user has login='admin' (set by fixture); user_code is
        # NULL on the seeded row -> resolver falls back to 'system'.
        assert row.actor_login == "admin"
        assert row.actor_code == "system"
        # No user_role_assignments rows in the test seed -> resolver
        # falls through tier 1 + tier 2, lands on 'user'.
        assert row.actor_role in ("user", "admin", "super_admin")
        # actor_id is the admin UUID.
        assert row.actor_id == "00000000-0000-0000-0000-000000000001"

    def test_response_row_uses_camel_case(
        self, client, admin_headers, db_session,
    ):
        r = client.post(
            "/api/v3/projects/create",
            headers=admin_headers,
            json={
                "name": "Camel Audit",
                "owner": "tmd1",
                "startDate": "2026-07-01T00:00:00+05:30",
                "endDate": "2026-12-31T00:00:00+05:30",
            },
        )
        pid = r.json()["data"]["id"]

        feed = client.get(
            f"/api/v3/projects/{pid}/audit-logs",
            headers=admin_headers,
        ).json()["data"]
        assert feed["total"] >= 1
        # Project block: identity moved out of per-row payload.
        proj = feed["project"]
        assert proj["projectId"] == pid
        assert proj["projectName"] == "Camel Audit"
        assert proj["projectCode"].startswith("UIDAI-PR")
        assert proj["projectStatus"]  # truthy
        assert proj["owner"] == "tmd1"
        # Pick the project.create row (newest-first ordering may include
        # other actions in future, but project.create will always be in
        # the response since it's the genesis event).
        creates = [
            e for e in feed["_embedded"]["elements"]
            if e["action"] == "project.create"
        ]
        assert creates, feed
        ev = creates[0]
        # Per-row payload — only audit-event-specific fields.
        assert "id" in ev
        assert "actorId" in ev
        assert "actorCode" in ev
        assert "actorLogin" in ev
        assert "actorRole" in ev
        assert "action" in ev
        assert "createdAt" in ev
        assert ev["actorLogin"] == "admin"
        assert ev["actorCode"] == "system"
        # Project identity must NOT be duplicated on the per-row payload
        # (it lives in the top-level project block).
        assert "projectName" not in ev
        assert "projectCode" not in ev
        assert "projectId" not in ev


class TestAuditSnapshotImmutability:
    def test_project_rename_does_not_mutate_existing_audit_row(
        self, client, admin_headers, db_session,
    ):
        # 1) Create
        r = client.post(
            "/api/v3/projects/create",
            headers=admin_headers,
            json={
                "name": "Initial Name",
                "owner": "tmd1",
                "startDate": "2026-07-01T00:00:00+05:30",
                "endDate": "2026-12-31T00:00:00+05:30",
            },
        )
        pid = r.json()["data"]["id"]
        create_row = (
            db_session.query(ProjectAuditLogModel)
            .filter(ProjectAuditLogModel.project_id == pid)
            .filter(ProjectAuditLogModel.action == "project.create")
            .first()
        )
        assert create_row is not None
        assert create_row.project_name == "Initial Name"

        # 2) Rename via PATCH
        r2 = client.patch(
            f"/api/v3/projects/{pid}",
            headers=admin_headers,
            json={"name": "Renamed Name"},
        )
        assert r2.status_code == 200, r2.text

        # 3) Refresh the in-session row and assert its snapshotted name
        # is still the original one (NOT NULL columns are immutable
        # snapshots, not live joins).
        db_session.refresh(create_row)
        assert create_row.project_name == "Initial Name"


class TestAuditLogsPagination:
    def test_pagination_offsets_and_total(
        self, client, admin_headers, db_session,
    ):
        # Create one project (writes one audit row) then patch it five
        # times to accumulate six audit rows.
        r = client.post(
            "/api/v3/projects/create",
            headers=admin_headers,
            json={
                "name": "Page Audit P",
                "owner": "tmd1",
                "startDate": "2026-07-01T00:00:00+05:30",
                "endDate": "2026-12-31T00:00:00+05:30",
            },
        )
        pid = r.json()["data"]["id"]
        for i in range(5):
            client.patch(
                f"/api/v3/projects/{pid}",
                headers=admin_headers,
                json={"description": f"rev-{i}"},
            )

        # Page 1 of 3
        page1 = client.get(
            f"/api/v3/projects/{pid}/audit-logs?offset=1&pageSize=3",
            headers=admin_headers,
        ).json()["data"]
        # Page 2 of 3
        page2 = client.get(
            f"/api/v3/projects/{pid}/audit-logs?offset=2&pageSize=3",
            headers=admin_headers,
        ).json()["data"]

        # We expect 6 rows total (1 create + 5 patches), so page-1 has 3
        # and page-2 has 3 (or less, in case some flow merges).
        assert page1["total"] == page2["total"] >= 6
        assert page1["pageSize"] == 3
        assert page1["offset"] == 1
        assert len(page1["_embedded"]["elements"]) == 3
        assert page2["offset"] == 2
        # Each page carries the (same) project block.
        assert page1["project"]["projectId"] == pid == page2["project"]["projectId"]
