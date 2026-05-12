"""Magic-byte content-sniff guard tests (mirror of monolith).

Covers ``app.shared.file_signature.detect_and_verify`` directly (unit
level) plus an integration smoke through the standalone-attachment
endpoint to confirm the wiring is intact.

Sample magic-byte snippets used here are hand-crafted (small bytes
prefixes). filetype only needs ~261 bytes for its widest signature so
tiny snippets are sufficient.
"""
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest

from app.core.errors import ValidationError
from app.core.config import settings
from app.infrastructure.db.models.milestone import MilestoneModel
from app.infrastructure.db.models.project import ProjectModel
from app.shared.file_signature import detect_and_verify


# ---------------------------------------------------------------------------
# Magic-byte / content snippets — minimal valid prefixes per format.
# ---------------------------------------------------------------------------
PDF_HEADER = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 8
GIF_HEADER = b"GIF89a" + b"\x00" * 8
ZIP_BYTES = b"PK\x05\x06" + b"\x00" * 18
PE_EXE = b"MZ\x90\x00" + b"\x00" * 60
ELF_BIN = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8


# ---------------------------------------------------------------------------
# Fixtures — inline temp storage + project/milestone helpers
# ---------------------------------------------------------------------------

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


# ===========================================================================
# Direct unit tests on detect_and_verify
# ===========================================================================

class TestDetectAndVerifyPositive:
    def test_valid_pdf(self):
        mime, ext = detect_and_verify(BytesIO(PDF_HEADER), "doc.pdf")
        assert mime == "application/pdf"
        assert ext == "pdf"

    def test_valid_jpeg(self):
        mime, _ = detect_and_verify(BytesIO(JPEG_HEADER), "photo.jpg")
        assert mime == "image/jpeg"

    def test_valid_png(self):
        mime, _ = detect_and_verify(BytesIO(PNG_HEADER), "img.png")
        assert mime == "image/png"

    def test_valid_gif(self):
        mime, _ = detect_and_verify(BytesIO(GIF_HEADER), "anim.gif")
        assert mime == "image/gif"

    def test_zip_as_docx_passes(self):
        mime, _ = detect_and_verify(BytesIO(ZIP_BYTES), "report.docx")
        assert mime == "application/zip"

    def test_zip_as_xlsx_passes(self):
        mime, _ = detect_and_verify(BytesIO(ZIP_BYTES), "data.xlsx")
        assert mime == "application/zip"

    def test_valid_text_ascii(self):
        mime, _ = detect_and_verify(
            BytesIO(b"Hello world\nThis is a plain text file."), "notes.txt",
        )
        assert mime == "text/plain"

    def test_valid_csv(self):
        mime, _ = detect_and_verify(
            BytesIO(b"id,name,value\n1,alpha,42\n"), "data.csv",
        )
        assert mime == "text/plain"

    def test_rewinds_stream(self):
        buf = BytesIO(PDF_HEADER)
        detect_and_verify(buf, "doc.pdf")
        assert buf.tell() == 0


class TestDetectAndVerifyNegative:
    def test_disguised_exe_as_pdf(self):
        with pytest.raises(ValidationError) as exc:
            detect_and_verify(BytesIO(PE_EXE), "evil.pdf")
        msg = str(exc.value).lower()
        assert "content does not match" in msg
        assert ".pdf" in msg

    def test_disguised_elf_as_docx(self):
        with pytest.raises(ValidationError):
            detect_and_verify(BytesIO(ELF_BIN), "evil.docx")

    def test_disguised_zip_as_pdf(self):
        with pytest.raises(ValidationError) as exc:
            detect_and_verify(BytesIO(ZIP_BYTES), "evil.pdf")
        assert "application/zip" in str(exc.value)

    def test_empty_file(self):
        with pytest.raises(ValidationError) as exc:
            detect_and_verify(BytesIO(b""), "empty.pdf")
        assert "empty" in str(exc.value).lower()

    def test_unknown_signature(self):
        with pytest.raises(ValidationError) as exc:
            detect_and_verify(BytesIO(b"random gibberish bytes"), "x.pdf")
        msg = str(exc.value).lower()
        assert "could not be recognised" in msg or "does not match" in msg

    def test_text_with_null_bytes_rejected(self):
        with pytest.raises(ValidationError) as exc:
            detect_and_verify(BytesIO(b"hello\x00world"), "evil.txt")
        assert "null" in str(exc.value).lower()

    def test_text_with_invalid_utf8(self):
        with pytest.raises(ValidationError) as exc:
            detect_and_verify(BytesIO(b"hi \xc3\x28 there"), "evil.csv")
        assert "utf-8" in str(exc.value).lower()


# ===========================================================================
# Integration smoke: HTTP path through milestone /attachments
# ===========================================================================

class TestUploadHTTPPath:
    def test_valid_pdf_upload_succeeds(
        self, client, admin_headers, milestone_id, temp_storage,
    ):
        r = client.post(
            f"/api/v3/milestones/{milestone_id}/attachments",
            headers=admin_headers,
            files={"file": ("doc.pdf", PDF_HEADER, "application/pdf")},
        )
        assert r.status_code == 201, r.text

    def test_disguised_exe_as_pdf_rejected(
        self, client, admin_headers, milestone_id, temp_storage,
    ):
        r = client.post(
            f"/api/v3/milestones/{milestone_id}/attachments",
            headers=admin_headers,
            files={"file": ("evil.pdf", PE_EXE, "application/pdf")},
        )
        assert r.status_code == 422, r.text
        body = r.json()
        assert "content does not match" in body["error"]["message"].lower()

    def test_text_with_null_bytes_via_http_rejected(
        self, client, admin_headers, milestone_id, temp_storage,
    ):
        r = client.post(
            f"/api/v3/milestones/{milestone_id}/attachments",
            headers=admin_headers,
            files={"file": ("evil.txt", b"hi\x00there", "text/plain")},
        )
        assert r.status_code == 422, r.text
        assert "null" in r.text.lower()
