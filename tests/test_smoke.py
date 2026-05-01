"""End-to-end smoke covering every business endpoint via TestClient.

Tests the full project-service surface against an in-memory SQLite DB
with a JWT minted locally via core.security.create_access_token.

Each test runs in isolation against a fresh in-memory DB (per the
db_engine fixture in conftest.py).
"""
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest

from app.core.config import settings
from app.infrastructure.db.models.activity import ActivityModel
from app.infrastructure.db.models.milestone import MilestoneModel
from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.resource_type import ResourceTypeModel
from app.infrastructure.db.models.subtask import SubtaskModel
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.models.vendor import VendorModel


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(scope="function")
def project_id(db_session, client, admin_headers):
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"UIDAI-PR{uuid4().hex[:14].upper()}",
        name=f"P-{uuid4().hex[:6]}",
        description="-",
        active=True, public=False, status="new",
        owner="tmd1", is_version=False,
        start_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p.id


@pytest.fixture(scope="function")
def milestone_id(db_session, project_id):
    m = MilestoneModel(
        id=str(uuid4()),
        project_id=project_id,
        name="M1",
        start_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 5, 30, tzinfo=timezone.utc),
        position=1, status="not_completed",
    )
    db_session.add(m)
    db_session.commit()
    return m.id


@pytest.fixture(scope="function")
def activity_id(db_session, project_id, milestone_id):
    a = ActivityModel(
        id=str(uuid4()),
        project_id=project_id, milestone_id=milestone_id,
        name="A1", type="standard",
        start_date=datetime(2026, 5, 2, tzinfo=timezone.utc),
        end_date=datetime(2026, 5, 10, tzinfo=timezone.utc),
        position=1, status="not_completed",
    )
    db_session.add(a)
    db_session.commit()
    return a.id


@pytest.fixture(scope="function")
def task_id(db_session, project_id, activity_id):
    t = TaskModel(
        id=str(uuid4()),
        project_id=project_id, activity_id=activity_id,
        name="T1", type="standard",
        start_date=datetime(2026, 5, 3, tzinfo=timezone.utc),
        end_date=datetime(2026, 5, 9, tzinfo=timezone.utc),
        position=1,
    )
    db_session.add(t)
    db_session.commit()
    return t.id


@pytest.fixture(scope="function")
def subtask_id(db_session, project_id, task_id):
    s = SubtaskModel(
        id=str(uuid4()),
        project_id=project_id, task_id=task_id,
        name="S1", type="standard",
        start_date=datetime(2026, 5, 4, tzinfo=timezone.utc),
        end_date=datetime(2026, 5, 8, tzinfo=timezone.utc),
        position=1,
    )
    db_session.add(s)
    db_session.commit()
    return s.id


@pytest.fixture(scope="function")
def vendor_id(db_session):
    v = VendorModel(
        id=str(uuid4()),
        name=f"V-{uuid4().hex[:6]}",
        active=True,
    )
    db_session.add(v)
    db_session.commit()
    return v.id


@pytest.fixture(scope="function")
def resource_type_id(db_session):
    rt = ResourceTypeModel(
        id=str(uuid4()),
        code=f"rt-{uuid4().hex[:4]}",
        name="RFP",
        active=True,
    )
    db_session.add(rt)
    db_session.commit()
    return rt.id


# ===========================================================================
# Resource types + Catalogs
# ===========================================================================


class TestResourceTypes:
    def test_list(self, client, admin_headers):
        r = client.get("/api/v3/resource_types", headers=admin_headers)
        assert r.status_code == 200


class TestCatalogs:
    def test_list_divisions(self, client, admin_headers):
        r = client.get("/api/v3/divisions", headers=admin_headers)
        assert r.status_code == 200

    def test_list_status_transitions(self, client, admin_headers):
        r = client.get(
            "/api/v3/project_status_transitions", headers=admin_headers,
        )
        assert r.status_code == 200


# ===========================================================================
# Vendors
# ===========================================================================


class TestVendors:
    def test_list(self, client, admin_headers):
        r = client.get("/api/v3/vendors", headers=admin_headers)
        assert r.status_code == 200

    def test_get(self, client, admin_headers, vendor_id):
        r = client.get(f"/api/v3/vendors/{vendor_id}", headers=admin_headers)
        assert r.status_code == 200

    def test_unknown_404(self, client, admin_headers):
        r = client.get(f"/api/v3/vendors/{uuid4()}", headers=admin_headers)
        assert r.status_code == 404


# ===========================================================================
# Projects (CRUD + lifecycle)
# ===========================================================================


class TestProjects:
    def test_list(self, client, admin_headers):
        r = client.get("/api/v3/projects", headers=admin_headers)
        assert r.status_code == 200

    def test_get(self, client, admin_headers, project_id):
        r = client.get(f"/api/v3/projects/{project_id}", headers=admin_headers)
        assert r.status_code == 200

    def test_get_unknown_404(self, client, admin_headers):
        r = client.get(f"/api/v3/projects/{uuid4()}", headers=admin_headers)
        assert r.status_code == 404


# ===========================================================================
# Milestones
# ===========================================================================


class TestMilestones:
    def test_list_under_project(self, client, admin_headers, project_id):
        r = client.get(
            f"/api/v3/projects/{project_id}/milestones", headers=admin_headers,
        )
        assert r.status_code == 200

    def test_get(self, client, admin_headers, milestone_id):
        r = client.get(
            f"/api/v3/milestones/{milestone_id}", headers=admin_headers,
        )
        assert r.status_code == 200

    def test_unknown_404(self, client, admin_headers):
        r = client.get(f"/api/v3/milestones/{uuid4()}", headers=admin_headers)
        assert r.status_code == 404


# ===========================================================================
# Activities
# ===========================================================================


class TestActivities:
    def test_list_under_milestone(self, client, admin_headers, milestone_id):
        r = client.get(
            f"/api/v3/milestones/{milestone_id}/activities",
            headers=admin_headers,
        )
        assert r.status_code == 200

    def test_get(self, client, admin_headers, activity_id):
        r = client.get(
            f"/api/v3/activities/{activity_id}", headers=admin_headers,
        )
        assert r.status_code == 200

    def test_unknown_404(self, client, admin_headers):
        r = client.get(f"/api/v3/activities/{uuid4()}", headers=admin_headers)
        assert r.status_code == 404


# ===========================================================================
# Tasks
# ===========================================================================


class TestTasks:
    def test_list_under_activity(self, client, admin_headers, activity_id):
        r = client.get(
            f"/api/v3/activities/{activity_id}/tasks", headers=admin_headers,
        )
        assert r.status_code == 200

    def test_get(self, client, admin_headers, task_id):
        r = client.get(f"/api/v3/tasks/{task_id}", headers=admin_headers)
        assert r.status_code == 200

    def test_unknown_404(self, client, admin_headers):
        r = client.get(f"/api/v3/tasks/{uuid4()}", headers=admin_headers)
        assert r.status_code == 404


# ===========================================================================
# Subtasks
# ===========================================================================


class TestSubtasks:
    def test_list_under_task(self, client, admin_headers, task_id):
        r = client.get(
            f"/api/v3/tasks/{task_id}/subtasks", headers=admin_headers,
        )
        assert r.status_code == 200

    def test_get(self, client, admin_headers, subtask_id):
        r = client.get(f"/api/v3/subtasks/{subtask_id}", headers=admin_headers)
        assert r.status_code == 200

    def test_unknown_404(self, client, admin_headers):
        r = client.get(f"/api/v3/subtasks/{uuid4()}", headers=admin_headers)
        assert r.status_code == 404


# ===========================================================================
# Tree
# ===========================================================================


class TestTree:
    def test_get(self, client, admin_headers, project_id):
        r = client.get(
            f"/api/v3/projects/{project_id}/tree", headers=admin_headers,
        )
        assert r.status_code == 200

    def test_unknown_404(self, client, admin_headers):
        r = client.get(
            f"/api/v3/projects/{uuid4()}/tree", headers=admin_headers,
        )
        assert r.status_code == 404


# ===========================================================================
# Comments
# ===========================================================================


class TestComments:
    def test_list_on_milestone(self, client, admin_headers, milestone_id):
        r = client.get(
            f"/api/v3/milestones/{milestone_id}/comments",
            headers=admin_headers,
        )
        assert r.status_code == 200

    def test_list_on_activity(self, client, admin_headers, activity_id):
        r = client.get(
            f"/api/v3/activities/{activity_id}/comments",
            headers=admin_headers,
        )
        assert r.status_code == 200

    def test_list_on_task(self, client, admin_headers, task_id):
        r = client.get(
            f"/api/v3/tasks/{task_id}/comments", headers=admin_headers,
        )
        assert r.status_code == 200

    def test_list_on_subtask(self, client, admin_headers, subtask_id):
        r = client.get(
            f"/api/v3/subtasks/{subtask_id}/comments", headers=admin_headers,
        )
        assert r.status_code == 200


# ===========================================================================
# Attachments
# ===========================================================================


@pytest.fixture(scope="function")
def temp_storage(tmp_path, monkeypatch):
    """Point storage at a per-test temp dir so uploads don't pollute /mnt."""
    monkeypatch.setattr(settings, "ATTACHMENTS_STORAGE_BASE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "ATTACHMENTS_SUBDIR_STRATEGY", "flat")
    from app.infrastructure.storage import file_storage
    file_storage._storage = None
    yield tmp_path
    file_storage._storage = None


class TestAttachments:
    def test_list_on_milestone(
        self, client, admin_headers, milestone_id, temp_storage,
    ):
        r = client.get(
            f"/api/v3/milestones/{milestone_id}/attachments",
            headers=admin_headers,
        )
        assert r.status_code == 200

    def test_upload_and_list(
        self, client, admin_headers, milestone_id, temp_storage,
    ):
        # Upload via multipart
        files = {"file": ("smoke.txt", BytesIO(b"hello"), "text/plain")}
        upload = client.post(
            f"/api/v3/milestones/{milestone_id}/attachments",
            headers=admin_headers,
            files=files,
        )
        assert upload.status_code == 201
        # List should include it
        r = client.get(
            f"/api/v3/milestones/{milestone_id}/attachments",
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 1


# ===========================================================================
# Auth
# ===========================================================================


class TestAuth:
    def test_unauthenticated_request_returns_401(self, client):
        r = client.get("/api/v3/projects")
        assert r.status_code == 401

    def test_health_no_auth_required(self, client):
        r = client.get("/health")
        assert r.status_code == 200
