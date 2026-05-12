"""Tests for project-level file attachments (mirror of monolith)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.config import settings
from app.infrastructure.db.models.project import ProjectModel


PDF_HEADER = b"%PDF-1.4 test\n"
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


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


# ---------------------------------------------------------------------------
# POST /projects/create (multipart variant)
# ---------------------------------------------------------------------------

class TestCreateProjectWithInlineAttachments:
    def test_json_create_unchanged(
        self, client, admin_headers, temp_storage,
    ):
        r = client.post(
            "/api/v3/projects/create",
            headers=admin_headers,
            json={
                "name": "JSON project",
                "owner": "tmd1",
                "startDate": "2026-07-01T00:00:00+05:30",
                "endDate": "2026-12-31T00:00:00+05:30",
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["name"] == "JSON project"
        # JSON path doesn't load attachments.
        assert "attachments" not in data

    def test_multipart_create_without_files_works(
        self, client, admin_headers, temp_storage,
    ):
        r = client.post(
            "/api/v3/projects/create",
            headers=admin_headers,
            data={
                "name": "Multipart no files",
                "owner": "tmd1",
                "startDate": "2026-07-01T00:00:00+05:30",
                "endDate": "2026-12-31T00:00:00+05:30",
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["name"] == "Multipart no files"
        assert data.get("attachments") == []

    def test_multipart_create_with_files_attaches(
        self, client, admin_headers, temp_storage,
    ):
        r = client.post(
            "/api/v3/projects/create",
            headers=admin_headers,
            data={
                "name": "Multipart with files",
                "owner": "tmd1",
                "startDate": "2026-07-01T00:00:00+05:30",
                "endDate": "2026-12-31T00:00:00+05:30",
            },
            files=[
                ("files", ("charter.pdf", PDF_HEADER, "application/pdf")),
                ("files", ("logo.png", PNG_HEADER, "image/png")),
            ],
        )
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        atts = data["attachments"]
        assert len(atts) == 2
        names = {a["filename"] for a in atts}
        assert names == {"charter.pdf", "logo.png"}
        mime_by_name = {a["filename"]: a["mimeType"] for a in atts}
        assert mime_by_name["charter.pdf"] == "application/pdf"
        assert mime_by_name["logo.png"] == "image/png"

    def test_multipart_create_rejects_disguised_exe(
        self, client, admin_headers, temp_storage,
    ):
        r = client.post(
            "/api/v3/projects/create",
            headers=admin_headers,
            data={
                "name": "Bad-file project",
                "owner": "tmd1",
                "startDate": "2026-07-01T00:00:00+05:30",
                "endDate": "2026-12-31T00:00:00+05:30",
            },
            files=[
                ("files", ("evil.pdf", b"MZ\x90\x00" + b"\x00" * 60,
                           "application/pdf")),
            ],
        )
        assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# GET /projects/{id}/attachments
# ---------------------------------------------------------------------------

class TestListProjectAttachments:
    def test_list_empty_initially(
        self, client, admin_headers, project_id, temp_storage,
    ):
        r = client.get(
            f"/api/v3/projects/{project_id}/attachments",
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["total"] == 0
        assert data["_embedded"]["elements"] == []

    def test_404_on_unknown_project(
        self, client, admin_headers, temp_storage,
    ):
        r = client.get(
            f"/api/v3/projects/{uuid4()}/attachments",
            headers=admin_headers,
        )
        assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# POST /projects/{id}/attachments
# ---------------------------------------------------------------------------

class TestUploadProjectAttachmentsAfterCreate:
    def test_upload_then_list(
        self, client, admin_headers, project_id, temp_storage,
    ):
        up = client.post(
            f"/api/v3/projects/{project_id}/attachments",
            headers=admin_headers,
            files=[("files", ("rfp.pdf", PDF_HEADER, "application/pdf"))],
        )
        assert up.status_code == 201, up.text
        created = up.json()["data"]
        assert created["total"] == 1
        assert created["_embedded"]["elements"][0]["filename"] == "rfp.pdf"

        listed = client.get(
            f"/api/v3/projects/{project_id}/attachments",
            headers=admin_headers,
        ).json()["data"]
        assert listed["total"] == 1
        assert listed["_embedded"]["elements"][0]["filename"] == "rfp.pdf"

    def test_empty_files_rejected(
        self, client, admin_headers, project_id, temp_storage,
    ):
        r = client.post(
            f"/api/v3/projects/{project_id}/attachments",
            headers=admin_headers,
            files=[],
        )
        assert r.status_code == 422, r.text
        assert "required" in r.text.lower()

    def test_disguised_file_rejected_post_create(
        self, client, admin_headers, project_id, temp_storage,
    ):
        r = client.post(
            f"/api/v3/projects/{project_id}/attachments",
            headers=admin_headers,
            files=[("files", ("evil.pdf",
                              b"MZ\x90\x00" + b"\x00" * 60,
                              "application/pdf"))],
        )
        assert r.status_code == 422, r.text

    def test_404_on_unknown_project(
        self, client, admin_headers, temp_storage,
    ):
        r = client.post(
            f"/api/v3/projects/{uuid4()}/attachments",
            headers=admin_headers,
            files=[("files", ("doc.pdf", PDF_HEADER, "application/pdf"))],
        )
        assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# GET /projects/{id} includes attachments[]
# ---------------------------------------------------------------------------

class TestProjectDetailIncludesAttachments:
    def test_attachments_eagerly_loaded(
        self, client, admin_headers, project_id, temp_storage,
    ):
        client.post(
            f"/api/v3/projects/{project_id}/attachments",
            headers=admin_headers,
            files=[("files", ("scope.pdf", PDF_HEADER, "application/pdf"))],
        )
        r = client.get(
            f"/api/v3/projects/{project_id}",
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        atts = r.json()["data"]["attachments"]
        assert len(atts) == 1
        assert atts[0]["filename"] == "scope.pdf"


# ---------------------------------------------------------------------------
# Delete flow — same DELETE /comments/{id} as M/A/T/S
# ---------------------------------------------------------------------------

class TestDeleteProjectAttachment:
    def test_delete_via_comment_endpoint(
        self, client, admin_headers, project_id, temp_storage,
    ):
        up = client.post(
            f"/api/v3/projects/{project_id}/attachments",
            headers=admin_headers,
            files=[("files", ("temp.pdf", PDF_HEADER, "application/pdf"))],
        )
        comment_id = up.json()["data"]["_embedded"]["elements"][0]["id"]
        r = client.delete(
            f"/api/v3/comments/{comment_id}",
            headers=admin_headers,
        )
        assert r.status_code in (200, 204), r.text
        listed = client.get(
            f"/api/v3/projects/{project_id}/attachments",
            headers=admin_headers,
        ).json()["data"]
        assert listed["total"] == 0
