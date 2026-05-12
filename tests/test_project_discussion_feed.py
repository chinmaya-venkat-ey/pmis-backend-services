"""Tests for ``GET /api/v3/projects/{project_uuid}/discussion-feed``.

Mirror of monolith's test_project_discussion_feed.py — same coverage:
404, empty tree, aggregation across the project tree, target name
resolution, soft-deleted filtering, ordering, and pagination.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.config import settings
from app.infrastructure.db.models.activity import ActivityModel
from app.infrastructure.db.models.milestone import MilestoneModel
from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.subtask import SubtaskModel
from app.infrastructure.db.models.task import TaskModel


PDF_HEADER = b"%PDF-1.4 test\n"


@pytest.fixture(scope="function")
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ATTACHMENTS_STORAGE_BASE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "ATTACHMENTS_SUBDIR_STRATEGY", "flat")
    from app.infrastructure.storage import file_storage
    file_storage._storage = None
    yield tmp_path
    file_storage._storage = None


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


def _make_milestone(db, project_id, name="M1"):
    m = MilestoneModel(
        id=str(uuid4()),
        project_id=project_id,
        name=name,
        position=0,
        status="not_completed",
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 12, 31),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _make_activity(db, project_id, milestone_id, name="A1"):
    a = ActivityModel(
        id=str(uuid4()),
        project_id=project_id,
        milestone_id=milestone_id,
        name=name,
        position=0,
        status="not_completed",
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 6, 30),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_task(db, project_id, activity_id, name="T1"):
    t = TaskModel(
        id=str(uuid4()),
        project_id=project_id,
        activity_id=activity_id,
        name=name,
        position=0,
        status="not_completed",
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 6, 30),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_subtask(db, project_id, task_id, name="S1"):
    s = SubtaskModel(
        id=str(uuid4()),
        project_id=project_id,
        task_id=task_id,
        name=name,
        position=0,
        status="not_completed",
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 6, 30),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ===========================================================================
# Tests
# ===========================================================================

class TestDiscussionFeedBasics:
    def test_404_on_unknown_project(self, client, admin_headers):
        r = client.get(
            f"/api/v3/projects/{uuid4()}/discussion-feed",
            headers=admin_headers,
        )
        assert r.status_code == 404, r.text

    def test_empty_project_tree_empty_feed(
        self, client, admin_headers, project_id,
    ):
        r = client.get(
            f"/api/v3/projects/{project_id}/discussion-feed",
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["total"] == 0
        assert data["_embedded"]["elements"] == []
        assert data["project"]["id"] == project_id


class TestDiscussionFeedAggregation:
    def test_collects_across_project_tree(
        self, client, admin_headers, project_id,
        db_session, temp_storage,
    ):
        m = _make_milestone(db_session, project_id, name="Milestone-A")
        a = _make_activity(
            db_session, project_id, m.id, name="Activity-A",
        )
        t = _make_task(
            db_session, project_id, a.id, name="Task-A",
        )
        s = _make_subtask(
            db_session, project_id, t.id, name="Subtask-A",
        )

        # 1) Project-level attachment.
        client.post(
            f"/api/v3/projects/{project_id}/attachments",
            headers=admin_headers,
            files=[("files", ("charter.pdf", PDF_HEADER, "application/pdf"))],
        )
        # 2) Milestone comment with body + file.
        client.post(
            f"/api/v3/milestones/{m.id}/comments",
            headers=admin_headers,
            data={"body": "Kicked off the milestone."},
            files=[("files", ("kickoff.pdf", PDF_HEADER, "application/pdf"))],
        )
        # 3) Activity comment body-only.
        client.post(
            f"/api/v3/activities/{a.id}/comments",
            headers=admin_headers,
            data={"body": "Stakeholder OK."},
        )
        # 4) Task standalone attachment (file-only).
        client.post(
            f"/api/v3/tasks/{t.id}/attachments",
            headers=admin_headers,
            files={"file": ("task-evidence.pdf", PDF_HEADER, "application/pdf")},
        )
        # 5) Subtask comment with body.
        client.post(
            f"/api/v3/subtasks/{s.id}/comments",
            headers=admin_headers,
            data={"body": "Subtask done."},
        )

        r = client.get(
            f"/api/v3/projects/{project_id}/discussion-feed",
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["total"] == 5
        kinds = {e["targetKind"] for e in data["_embedded"]["elements"]}
        assert kinds == {"project", "milestone", "activity", "task", "subtask"}

    def test_target_names_resolved(
        self, client, admin_headers, project_id,
        db_session, temp_storage,
    ):
        m = _make_milestone(db_session, project_id, name="Naming Test M")
        client.post(
            f"/api/v3/milestones/{m.id}/comments",
            headers=admin_headers,
            data={"body": "test"},
        )
        r = client.get(
            f"/api/v3/projects/{project_id}/discussion-feed",
            headers=admin_headers,
        )
        row = r.json()["data"]["_embedded"]["elements"][0]
        assert row["targetKind"] == "milestone"
        assert row["targetName"] == "Naming Test M"
        assert row["body"] == "test"

    def test_each_row_carries_body_and_attachments_fields(
        self, client, admin_headers, project_id, temp_storage,
    ):
        client.post(
            f"/api/v3/projects/{project_id}/attachments",
            headers=admin_headers,
            files=[("files", ("a.pdf", PDF_HEADER, "application/pdf"))],
        )
        r = client.get(
            f"/api/v3/projects/{project_id}/discussion-feed",
            headers=admin_headers,
        )
        row = r.json()["data"]["_embedded"]["elements"][0]
        assert (row.get("body") or "") == ""
        assert len(row["attachments"]) == 1
        assert row["attachments"][0]["filename"] == "a.pdf"


class TestDiscussionFeedFiltering:
    def test_soft_deleted_comment_excluded(
        self, client, admin_headers, project_id,
        db_session, temp_storage,
    ):
        m = _make_milestone(db_session, project_id)
        up = client.post(
            f"/api/v3/milestones/{m.id}/comments",
            headers=admin_headers,
            data={"body": "soon to be deleted"},
        )
        cid = up.json()["data"]["id"]
        client.delete(f"/api/v3/comments/{cid}", headers=admin_headers)
        client.post(
            f"/api/v3/milestones/{m.id}/comments",
            headers=admin_headers,
            data={"body": "this one stays"},
        )

        r = client.get(
            f"/api/v3/projects/{project_id}/discussion-feed",
            headers=admin_headers,
        )
        data = r.json()["data"]
        bodies = [e["body"] for e in data["_embedded"]["elements"]]
        assert bodies == ["this one stays"]

    def test_soft_deleted_target_excluded(
        self, client, admin_headers, project_id,
        db_session, temp_storage,
    ):
        m = _make_milestone(db_session, project_id, name="Doomed M")
        client.post(
            f"/api/v3/milestones/{m.id}/comments",
            headers=admin_headers,
            data={"body": "soon to be orphaned"},
        )
        m.deleted_at = datetime.now(timezone.utc)
        db_session.commit()

        r = client.get(
            f"/api/v3/projects/{project_id}/discussion-feed",
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 0


class TestDiscussionFeedOrderingAndPagination:
    def test_ordered_by_created_at_descending(
        self, client, admin_headers, project_id,
        db_session, temp_storage,
    ):
        """Write three comment rows directly with explicit ``created_at``
        values 10s apart so the test doesn't depend on insert-time clock
        resolution."""
        from app.infrastructure.db.models.comment import CommentModel
        # Reuse the seeded admin uuid from conftest so the comment row's
        # author_user_id FK is valid.
        from tests.conftest import _ADMIN_UUID, _seed_user_with_role
        _seed_user_with_role(
            db_session, _ADMIN_UUID, "admin", "admin@example.com", "admin",
        )
        m = _make_milestone(db_session, project_id)
        base = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
        for offset_secs, body in [(0, "first"), (10, "second"), (20, "third")]:
            db_session.add(CommentModel(
                id=str(uuid4()),
                target_kind="milestone",
                target_id=m.id,
                body=body,
                attachments=None,
                author_user_id=_ADMIN_UUID,
                created_at=base.replace(second=offset_secs),
            ))
        db_session.commit()

        r = client.get(
            f"/api/v3/projects/{project_id}/discussion-feed",
            headers=admin_headers,
        )
        elements = r.json()["data"]["_embedded"]["elements"]
        bodies = [e["body"] for e in elements]
        assert bodies == ["third", "second", "first"]
        timestamps = [e["createdAt"] for e in elements]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_pagination(
        self, client, admin_headers, project_id,
        db_session, temp_storage,
    ):
        m = _make_milestone(db_session, project_id)
        for i in range(7):
            client.post(
                f"/api/v3/milestones/{m.id}/comments",
                headers=admin_headers,
                data={"body": f"c{i}"},
            )
        page1 = client.get(
            f"/api/v3/projects/{project_id}/discussion-feed"
            f"?offset=1&pageSize=3",
            headers=admin_headers,
        ).json()["data"]
        page3 = client.get(
            f"/api/v3/projects/{project_id}/discussion-feed"
            f"?offset=3&pageSize=3",
            headers=admin_headers,
        ).json()["data"]

        assert page1["total"] == 7
        assert len(page1["_embedded"]["elements"]) == 3
        assert len(page3["_embedded"]["elements"]) == 1
