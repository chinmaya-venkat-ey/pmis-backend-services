"""End-to-end smoke against every endpoint family.

Overrides controllers via FastAPI's ``dependency_overrides`` and returns
REAL Pydantic response instances (not MagicMock attribute proxies), so
the routes' ``response_model`` validation passes and the HAL wrapper
runs through cleanly.

The assertions match the monolith's wire contract — response data lives
under ``json()["data"]`` and uses **camelCase** keys (``projectCode``,
``startDate``, etc.).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.schemas.comment import CommentDeleteSuccess, CommentResponse
from app.schemas.milestone import MilestoneResponse
from app.schemas.project import ProjectResponse


IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 5, 15, tzinfo=IST)
LATER = datetime(2026, 6, 15, tzinfo=IST)


def _project() -> ProjectResponse:
    return ProjectResponse(
        id="p1", project_code="UIDAI-PR000", name="P1",
        description=None, active=True, public=False, is_public=False,
        status_explanation=None, parent_id=None,
        status="new", owner="tmd1",
        owner_other=None, category=None, category_other=None,
        category_other_reason=None,
        start_date=None, end_date=None,
        actual_start_date=None, actual_end_date=None,
        created_at=NOW, updated_at=NOW,
        created_by=None, updated_by=None,
        deleted_at=None, deleted_by=None,
        vendors=[], vendor_ids=[],
    )


def _milestone() -> MilestoneResponse:
    return MilestoneResponse(
        id="m1", project_id="p1", name="M1", description=None,
        start_date=NOW, end_date=LATER,
        actual_start_date=None, actual_end_date=None,
        position=1, status="not_completed", priority=None,
        created_at=NOW, updated_at=NOW, deleted_at=None,
        depends_on=[], vendor_ids=[],
    )


def _comment() -> CommentResponse:
    return CommentResponse(
        id="c1", target_kind="milestone", target_id="m1",
        body="hi", attachments=None, author_user_id="test-admin-id",
        created_at=NOW, updated_at=NOW,
        deleted_at=None, deleted_by=None,
    )


# ----- Project ------------------------------------------------------------

@pytest.fixture
def project_ctrl_override(app):
    from app.dependencies import get_project_controller

    fake = MagicMock()
    proj = _project()
    for m in ("create", "get", "save", "publish", "close", "delete"):
        getattr(fake, m).return_value = proj
    fake.list_.return_value = {
        "items": [], "total": 0, "offset": 1, "page_size": 20,
    }
    fake.upsert.return_value = (proj, True)
    fake.audit_logs.return_value = {
        "project": {
            "project_id": "p1", "project_code": "X", "project_name": "P1",
            "project_status": "new", "owner": "tmd1",
        },
        "total": 0, "offset": 1, "page_size": 50, "elements": [],
    }
    fake.discussion_feed.return_value = {
        "project": {"id": "p1", "name": "P1"},
        "total": 0, "offset": 1, "page_size": 50, "elements": [],
    }
    fake.role_assignments.return_value = {
        "project_id": "p1", "project_name": "P1", "roles": [],
    }
    fake.assignable_users.return_value = {
        "project_id": "p1", "project_name": "P1", "users": [],
    }
    fake.list_attachments.return_value = {"total": 0, "elements": []}

    app.dependency_overrides[get_project_controller] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_project_controller, None)


class TestProjectEndpoints:
    """Match monolith's TestCreateProject / TestSaveProject / TestPublishProject /
    TestCloseProject / TestUpsert / TestDeleteProject — same paths, same
    response-shape assertions, only the URL prefix differs (/api/v3/ →
    /project/)."""

    def test_create_returns_201_with_project_data(self, client, project_ctrl_override):
        r = client.post(
            "/project/projects/create",
            json={"name": "P1", "owner": "tmd1", "vendor_ids": []},
        )
        assert r.status_code == 201
        data = r.json()["data"]
        # camelCased keys mirror monolith.
        assert data["_type"] == "Project"
        assert data["name"] == "P1"
        assert data["projectCode"].startswith("UIDAI-PR")
        # vendors[] embed is present (even when empty) — monolith parity.
        assert data["vendors"] == []
        # isPublic mirror of public.
        assert "isPublic" in data

    def test_get_returns_project_camelcase(self, client, project_ctrl_override):
        r = client.get("/project/projects/p1")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["_type"] == "Project"
        assert data["id"] == "p1"

    def test_list_returns_hal_collection(self, client, project_ctrl_override):
        r = client.get("/project/projects")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["_type"] == "Collection"
        assert data["_embedded"]["elements"] == []

    def test_list_all_returns_hal_collection(self, client, project_ctrl_override):
        r = client.get("/project/projects/all")
        assert r.status_code == 200
        assert r.json()["data"]["_type"] == "Collection"

    def test_save_returns_project(self, client, project_ctrl_override):
        r = client.post("/project/projects/p1/save")
        assert r.status_code == 200
        assert r.json()["data"]["_type"] == "Project"

    def test_publish_returns_project(self, client, project_ctrl_override):
        r = client.post("/project/projects/p1/publish")
        assert r.status_code == 200

    def test_close_with_reason_returns_project(self, client, project_ctrl_override):
        r = client.post("/project/projects/p1/close", json={"reason": "done"})
        assert r.status_code == 200
        assert r.json()["data"]["_type"] == "Project"

    def test_close_no_body_returns_project(self, client, project_ctrl_override):
        r = client.post("/project/projects/p1/close")
        assert r.status_code == 200

    def test_upsert_insert_returns_201_with_created_true(
        self, client, project_ctrl_override,
    ):
        r = client.put(
            "/project/projects/p-new",
            json={"name": "PN", "owner": "tmd1"},
        )
        assert r.status_code == 201
        # Monolith parity: data carries ``_created: true`` on insert.
        assert r.json()["data"]["_created"] is True

    def test_upsert_update_returns_200_with_created_false(
        self, client, project_ctrl_override,
    ):
        project_ctrl_override.upsert.return_value = (_project(), False)
        r = client.put(
            "/project/projects/p1",
            json={"name": "P1", "owner": "tmd1"},
        )
        assert r.status_code == 200
        assert r.json()["data"]["_created"] is False

    def test_audit_logs_returns_envelope(self, client, project_ctrl_override):
        r = client.get("/project/projects/p1/audit-logs")
        assert r.status_code == 200
        data = r.json()["data"]
        # camelCase: project_id -> projectId
        assert "project" in data
        assert "elements" in data

    def test_discussion_feed_returns_envelope(self, client, project_ctrl_override):
        r = client.get("/project/projects/p1/discussion-feed")
        assert r.status_code == 200

    def test_role_assignments(self, client, project_ctrl_override):
        r = client.get("/project/projects/p1/role-assignments")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["projectId"] == "p1"
        assert data["roles"] == []

    def test_assignable_users(self, client, project_ctrl_override):
        r = client.get("/project/projects/p1/assignable-users")
        assert r.status_code == 200
        assert r.json()["data"]["users"] == []

    def test_attachments_list(self, client, project_ctrl_override):
        r = client.get("/project/projects/p1/attachments")
        assert r.status_code == 200

    def test_delete_returns_204(self, client, project_ctrl_override):
        r = client.delete("/project/projects/p1")
        assert r.status_code == 204


# ----- Milestone ----------------------------------------------------------

@pytest.fixture
def milestone_ctrl_override(app):
    from app.dependencies import get_milestone_controller

    fake = MagicMock()
    payload = _milestone()
    for m in ("create", "get", "delete", "restore"):
        getattr(fake, m).return_value = payload
    fake.list_for_project.return_value = {
        "items": [], "total": 0, "offset": 1, "page_size": 50,
    }
    app.dependency_overrides[get_milestone_controller] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_milestone_controller, None)


class TestMilestoneEndpoints:

    def test_create_returns_201(self, client, milestone_ctrl_override):
        r = client.post(
            "/project/projects/p1/milestones/create",
            json={
                "name": "M1",
                "start_date": "2026-05-15T00:00:00+05:30",
                "end_date": "2026-06-15T00:00:00+05:30",
                "priority": "P2",
                "depends_on": [], "vendor_ids": [],
            },
        )
        assert r.status_code == 201
        data = r.json()["data"]
        assert data["_type"] == "Milestone"
        # camelCase mirror of project_id, start_date, etc.
        assert "projectId" in data
        assert "startDate" in data

    def test_list(self, client, milestone_ctrl_override):
        r = client.get("/project/projects/p1/milestones")
        assert r.status_code == 200

    def test_get(self, client, milestone_ctrl_override):
        r = client.get("/project/milestones/m1")
        assert r.status_code == 200

    def test_delete_returns_204(self, client, milestone_ctrl_override):
        r = client.delete("/project/milestones/m1")
        assert r.status_code == 204

    def test_restore(self, client, milestone_ctrl_override):
        r = client.post("/project/milestones/m1/restore")
        assert r.status_code == 200


# ----- Comments + Attachments --------------------------------------------

@pytest.fixture
def comment_ctrl_override(app):
    from app.dependencies import get_comment_controller

    fake = MagicMock()
    payload = _comment()
    fake.create_multipart.return_value = payload
    fake.list_for_target.return_value = {
        "items": [], "total": 0, "offset": 1, "page_size": 50,
    }
    # Monolith parity: DELETE /comments/{id} returns a Success envelope
    # (``{_type: "Success", message: "Comment <uuid> deleted."}``) — not
    # the full Comment row.
    fake.delete.return_value = CommentDeleteSuccess(
        message="Comment c1 deleted.",
    )
    app.dependency_overrides[get_comment_controller] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_comment_controller, None)


class TestCommentEndpoints:

    def test_create_multipart_body_only(self, client, comment_ctrl_override):
        r = client.post(
            "/project/milestones/m1/comments",
            data={"body": "hello"},
        )
        assert r.status_code == 201
        data = r.json()["data"]
        assert data["_type"] == "Comment"
        assert "targetKind" in data

    def test_list(self, client, comment_ctrl_override):
        r = client.get("/project/milestones/m1/comments")
        assert r.status_code == 200

    def test_delete(self, client, comment_ctrl_override):
        r = client.delete("/project/comments/c1")
        assert r.status_code == 200


@pytest.fixture
def attachment_ctrl_override(app):
    from app.dependencies import get_attachment_controller

    fake = MagicMock()
    # Monolith parity: DELETE /attachments/{id} returns the same Success
    # envelope as DELETE /comments/{id}, but with the attachment-specific
    # message wording.
    fake.delete.return_value = CommentDeleteSuccess(
        message="Attachment c1 deleted.",
    )
    fake.list_for_target.return_value = {"total": 0, "elements": []}
    app.dependency_overrides[get_attachment_controller] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_attachment_controller, None)


class TestAttachmentEndpoints:

    def test_list_for_milestone(self, client, attachment_ctrl_override):
        r = client.get("/project/milestones/m1/attachments")
        assert r.status_code == 200

    def test_delete(self, client, attachment_ctrl_override):
        r = client.delete("/project/attachments/c1")
        assert r.status_code == 200


# ----- Tree + Dashboard --------------------------------------------------

def test_tree_get(client, app):
    from app.dependencies import get_tree_controller

    fake = MagicMock()
    fake.get_tree.return_value = {
        "_type": "ProjectTree", "_links": {}, "project": {},
        "counts": {}, "milestones": [],
    }
    app.dependency_overrides[get_tree_controller] = lambda: fake
    try:
        r = client.get("/project/projects/p1/tree")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_tree_controller, None)


def test_dashboard_summary(client, app):
    from app.dependencies import get_dashboard_controller

    fake = MagicMock()
    fake.summary.return_value = {
        "asOf": "2026-05-15", "delayMinDays": 5, "counts": {},
        "delayedTrack": [], "topOrganisations": [], "topDivisions": [],
    }
    app.dependency_overrides[get_dashboard_controller] = lambda: fake
    try:
        r = client.get("/project/dashboard/summary")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_dashboard_controller, None)
