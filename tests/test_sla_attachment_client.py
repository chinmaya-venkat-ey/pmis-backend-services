"""Unit tests for the pmis-file-store client and attachment schemas.

The DB layer is exercised by the existing live-DB smoke scripts; this
module covers the layers that are pure Python — the HTTP client adapter
and the Pydantic schemas — so they can run in CI without any external
service.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.clients import FileStoreClient, FileStoreUnavailable
from app.schemas.sla_attachment import (
    ALLOWED_IMAGE_MIMES,
    SlaAttachmentCaptionUpdate,
    SlaAttachmentResponse,
)


# --------------------------------------------------------------------------- schemas


def test_allowed_mimes_include_common_image_types():
    # If we ever drop one of these the FE picker text needs updating too;
    # the test exists so the change is intentional, not accidental.
    assert "image/png" in ALLOWED_IMAGE_MIMES
    assert "image/jpeg" in ALLOWED_IMAGE_MIMES
    assert "image/webp" in ALLOWED_IMAGE_MIMES


def test_caption_update_accepts_null_and_string():
    SlaAttachmentCaptionUpdate(caption=None)
    SlaAttachmentCaptionUpdate(caption="cover image")
    with pytest.raises(Exception):
        SlaAttachmentCaptionUpdate(caption="x" * 600)  # > 500 cap


def test_attachment_response_round_trip():
    r = SlaAttachmentResponse(
        id="a", sla_id="b", file_id="c",
        file_url="http://example.com/x.png",
        original_filename="x.png", mime_type="image/png",
        size_bytes=1, caption="hi",
    )
    dumped = r.model_dump()
    assert dumped["file_id"] == "c"
    assert dumped["file_url"].endswith(".png")


# --------------------------------------------------------------------------- client


def _make_response(status: int, body: dict | str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = body if isinstance(body, str) else "..."
    resp.json.return_value = body if isinstance(body, dict) else {}
    return resp


def test_upload_happy_path_returns_stored_file():
    client = FileStoreClient(base_url="http://file-svc:8005", token="svc")
    fake_body = {
        "data": {
            "file_id": "FID-123",
            "download_url": "http://s3/x.png?sig=abc",
            "original_filename": "x.png",
            "mime_type": "image/png",
            "size_bytes": 4,
            "expires_in_seconds": 3600,
        }
    }
    with patch("httpx.Client") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value.post.return_value = (
            _make_response(201, fake_body)
        )
        result = client.upload(
            io.BytesIO(b"PNG"), "x.png", "image/png",
            entity_type="contract.sla", entity_id="PMU-SLA001",
        )
    assert result.file_id == "FID-123"
    assert result.download_url.startswith("http://s3/")
    assert result.expires_in_seconds == 3600


def test_upload_connection_failure_raises_unavailable():
    client = FileStoreClient(base_url="http://file-svc:8005", token="svc")
    with patch("httpx.Client") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value.post.side_effect = (
            httpx.RequestError("connection refused")
        )
        with pytest.raises(FileStoreUnavailable):
            client.upload(io.BytesIO(b"x"), "x.png", "image/png")


def test_upload_5xx_raises_unavailable():
    client = FileStoreClient(base_url="http://file-svc:8005", token="svc")
    with patch("httpx.Client") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value.post.return_value = (
            _make_response(503, "upstream down")
        )
        with pytest.raises(FileStoreUnavailable):
            client.upload(io.BytesIO(b"x"), "x.png", "image/png")


def test_refresh_url_returns_new_signed_url():
    client = FileStoreClient(base_url="http://file-svc:8005", token="svc")
    fake_body = {
        "data": {
            "download_url": "http://s3/new?sig=zzz",
            "expires_in_seconds": 1800,
        }
    }
    with patch("httpx.Client") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value.get.return_value = (
            _make_response(200, fake_body)
        )
        result = client.refresh_url("FID-123")
    assert result.download_url.endswith("sig=zzz")
    assert result.expires_in_seconds == 1800


def test_delete_swallows_5xx_and_returns_false():
    # Filestore delete is best-effort — our row already removed.
    client = FileStoreClient(base_url="http://file-svc:8005", token="svc")
    with patch("httpx.Client") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value.delete.return_value = (
            _make_response(500, "boom")
        )
        assert client.delete("FID-123") is False


def test_delete_happy_path_returns_true():
    client = FileStoreClient(base_url="http://file-svc:8005", token="svc")
    with patch("httpx.Client") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value.delete.return_value = (
            _make_response(200, {"data": {"message": "deleted"}})
        )
        assert client.delete("FID-123") is True


def test_per_request_bearer_overrides_service_token():
    client = FileStoreClient(base_url="http://file-svc:8005", token="service-tok")
    captured: dict = {}

    def _post(url, headers=None, files=None, data=None):
        captured["headers"] = dict(headers or {})
        return _make_response(201, {"data": {
            "file_id": "x", "download_url": "u", "size_bytes": 1,
        }})

    with patch("httpx.Client") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value.post.side_effect = _post
        client.upload(
            io.BytesIO(b"x"), "x.png", "image/png",
            bearer_token="user-tok",
        )
    assert captured["headers"]["Authorization"] == "Bearer user-tok"
